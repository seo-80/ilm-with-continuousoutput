import numpy as np
import xarray as xr
from scipy.special import digamma, gammaln, gamma
def logB(W, nu):
    D = W.shape[-1]
    return D * np.log(2) + D * digamma(nu/2) - nu/2 * np.linalg.slogdet(W)[1]

def logC(alpha):
    return gammaln(alpha.sum()) - gammaln(alpha).sum()

def multi_student_t(X, m, L, nu):
    D = X.shape[1]
    diff = X - m
    log_part1 = gammaln((nu + D)/2)
    log_part2 = -gammaln(nu/2)
    log_part3 = -D/2 * np.log(nu*np.pi)
    log_part4 = -0.5 * np.log(np.linalg.det(L))
    log_part5 = -(nu+D)/2 * np.log(1 + 1/nu * np.einsum("nj,jk,nk->n", diff, np.linalg.inv(L), diff))

    # Calculate the log of the final result
    log_result = log_part1 + log_part2 + log_part3 + log_part4 + log_part5

    # Convert the log result back to a regular number
    result = np.exp(log_result)
        # print("Part 5:", part5)
    
    return result
    # return gamma((nu + D)/2) / (gamma(nu/2) * np.power(nu*np.pi, D/2) * np.sqrt(np.linalg.det(L))) * np.power(1 + 1/nu * np.einsum("nj,jk,nk->n", diff, np.linalg.inv(L), diff), -(nu+D)/2)


class BayesianGaussianMixtureModel:
    # todo : add pi_mixture_ratio, c_alpha, mixture_pi
    def __init__(self, K, D, alpha0, beta0, nu0, m0, W0, c_alpha, pi_mixture_ratio=None):
        self.K = K
        self.D = D
        if isinstance(alpha0, (int, float, complex)):
            self.alpha0 = alpha0 * np.ones(K)
        elif alpha0.shape == (K,):
            self.alpha0 = alpha0
        else:
            raise ValueError("The shape of alpha0 is invalid.")
        if isinstance(c_alpha, (int, float, complex)):
            self.c_alpha = c_alpha * np.ones(K)
        elif isinstance(c_alpha, np.ndarray) :
            self.c_alpha = c_alpha
            if c_alpha.shape == (K,):
                self.mixture_pi = False
            elif c_alpha.shape[1] == K:
                self.mixture_pi = True
                self.comopnent_num = c_alpha.shape[0]
                self.pi_mixture_ratio = pi_mixture_ratio if pi_mixture_ratio is not None else np.ones(self.comopnent_num)/self.comopnent_num
            else:
                raise ValueError("The shape of c_alpha is invalid.")
        else:
            raise ValueError("The shape of c_alpha is invalid.")
        self.beta0 = beta0
        self.nu0 = nu0
        if m0.shape == (D,):
            self.m0 = np.tile(m0, (K, 1))
        elif m0.shape == (K, D):
            self.m0 = m0
        else:
            raise ValueError("The shape of m0 is invalid.")
        self.W0 = W0
        

        self.alpha = None
        self.beta = None
        self.nu = None
        self.m = None
        self.W = None
        self.lower_bound = None
        self.X = None
        self._init_params()

    def _init_params(self, X=None, random_state=None):
        '''
        Method for initializing model parameterse based on the size and variance of the input data array. 

        Parameters
        ----------
        X : 2D numpy array
            2D numpy array representing input data, where X[n, i] represents the i-th element of n-th point in X.
        random_state : int
            int, specifying the seed for random initialization of m
        '''
        if X is None:
            N, D = 1, self.D
        else:
            N, D = X.shape
        rnd = np.random.RandomState(seed=random_state)

        
        self.alpha = self.alpha0 + N / self.K * np.ones(self.K)
        self.beta = (self.beta0 + N / self.K) * np.ones(self.K)
        self.nu = (self.nu0 + N / self.K) * np.ones(self.K)
        self.m = self.m0 
        self.W = np.tile(self.W0, (self.K, 1, 1))
        # print('alpha',self.alpha)
        # print('beta',self.beta)
        # print('nu',self.nu)
        # print('m',self.m)
        # print('W',self.W)

    def _e_like_step(self, X):
        '''
        Method for calculating the array corresponding to responsibility.

        Parameters
        ----------
        X : 2D numpy array
            2D numpy array representing input data, where X[n, i] represents the i-th element of n-th point in X.

        Returns
        ----------
        r : 2D numpy array
            2D numpy array representing responsibility of each component for each sample in X, 
            where r[n, k] = $r_{n, k}$.

        '''
        N, _ = np.shape(X)

        if self.c_alpha is None:
            tpi = np.exp( digamma(self.alpha) - digamma(self.alpha.sum()) )
        else:
            if self.mixture_pi:
                tpi = np.sum(self.c_alpha, axis=0)/np.sum(self.c_alpha)
            else:
                tpi = self.c_alpha/np.sum(self.c_alpha)

        arg_digamma = np.reshape(self.nu, (self.K, 1)) - np.reshape(np.arange(0, self.D, 1), (1, self.D))
        tlam = np.exp( digamma(arg_digamma/2).sum(axis=1)  + self.D * np.log(2) + np.log(np.linalg.det(self.W)) )

        diff = np.reshape(X, (N, 1, self.D) ) - np.reshape(self.m, (1, self.K, self.D) )
        exponent = self.D / self.beta + self.nu * np.einsum("nkj,nkj->nk", np.einsum("nki,kij->nkj", diff, self.W), diff)

        exponent_subtracted = exponent - np.reshape(exponent.min(axis=1), (N, 1))
        rho = tpi*np.sqrt(tlam)*np.exp( -0.5 * exponent_subtracted )
        r = rho/np.reshape(rho.sum(axis=1), (N, 1))

        return r


    def _m_like_step(self, X, r):
        '''
        Method for calculating the model parameters based on the responsibility.

        Parameters
        ----------
        X : 2D numpy array
            2D numpy array representing input data, where X[n, i] represents the i-th element of n-th point in X.
        r : 2D numpy array
            2-D numpy array representing responsibility of each component for each sample in X, 
            where r[n, k] = $r_{n, k}$.
        '''
        N, _ = np.shape(X)
        n_samples_in_component = r.sum(axis=0)
        barx = r.T @ X / np.reshape(n_samples_in_component, (self.K, 1))
        diff = np.reshape(X, (N, 1, self.D) ) - np.reshape(barx, (1, self.K, self.D) )
        S = np.einsum("nki,nkj->kij", np.einsum("nk,nki->nki", r, diff), diff) / np.reshape(n_samples_in_component, (self.K, 1, 1))

        self.alpha = self.alpha0 + n_samples_in_component
        self.beta = self.beta0 + n_samples_in_component
        self.nu = self.nu0 + n_samples_in_component
        self.m = (self.m0 * self.beta0 + barx * np.reshape(n_samples_in_component, (self.K, 1)))/np.reshape(self.beta, (self.K, 1))

        diff2 = barx - self.m0
        Winv = np.reshape(np.linalg.inv( self.W0 ), (1, self.D, self.D)) + \
            S * np.reshape(n_samples_in_component, (self.K, 1, 1)) + \
            np.reshape( self.beta0 * n_samples_in_component / (self.beta0 + n_samples_in_component), (self.K, 1, 1)) * np.einsum("ki,kj->kij",diff2,diff2) 
        self.W = np.linalg.inv(Winv)

    def _calc_lower_bound(self, r):
        '''
        Method for calculating the variational lower bound.

        Parameters
        ----------
        r : 2D numpy array
            2-D numpy array representing responsibility of each component for each sample in X, 
            where r[n, k] = $r_{n, k}$.
        Returns
        ----------
        lower_bound : float
            The variational lower bound, where the final constant term is omitted.
        '''
        return - (r * np.log(r)).sum() + \
            logC(self.alpha0) - logC(self.alpha) +\
            self.D/2 * (self.K * np.log(self.beta0) - np.log(self.beta).sum()) + \
            self.K * logB(self.W0, self.nu0) - logB(self.W, self.nu).sum()


    def fit(self, data, max_iter=1e3, tol=1e-4, random_state=None, disp_message=False):
        '''
        Method for fitting the model.

        Parameters
        ----------
        X : 2D numpy array
            2D numpy array representing input data, where X[n, i] represents the i-th element of n-th point in X.
        max_iter : int
            The maximum number of iteration
        tol : float
            The criterion for juding the convergence. 
            When the change of lower bound becomes smaller than tol, the iteration is stopped.
        random_state : int
            An integer specifying the random number seed for random initialization
        disp_message : Boolean
            Whether to show the message on the result.
        '''
        if self.X is None:
            self.X = data.X.values
            if len(self.X.shape) == 1:
                self.X = self.X.reshape(1, -1)
            self._init_params(self.X, random_state=random_state)
        else:
            self.X = np.vstack([self.X, data.X.values])

        r = self._e_like_step(self.X)
        lower_bound = self._calc_lower_bound(r)

        for i in range(max_iter):
            self._m_like_step(self.X, r)
            r = self._e_like_step(self.X)

            lower_bound_prev = lower_bound
            lower_bound = self._calc_lower_bound(r)

            if abs(lower_bound - lower_bound_prev) < tol:
                break

        self.lower_bound = lower_bound

        if disp_message:
            print(f"n_iter : {i}")
            print(f"convergend : {i < max_iter}")
            print(f"lower bound : {lower_bound}")
            print(f"Change in the variational lower bound : {lower_bound - lower_bound_prev}")

    def fit_from_agent(self, source_agent, N, max_iter=1e3, tol=1e-4, random_state=None, disp_message=False):
        '''
        Method for fitting the model based on the source agent.

        Parameters
        ----------
        source_agent : BayesianGaussianMixtureModel
            An instance of BayesianGaussianMixtureModel, which is used as the source of the training data.
        N : int
            The number of samples to be generated.
        max_iter : int
            The maximum number of iteration
        tol : float
            The criterion for juding the convergence. 
            When the change of lower bound becomes smaller than tol, the iteration is stopped.
        random_state : int
            An integer specifying the random number seed for random initialization
        disp_message : Boolean
            Whether to show the message on the result.
        '''
        X = source_agent.generate(N)
        self.fit(X=X, max_iter=max_iter, tol=tol, random_state=random_state, disp_message=disp_message)
    def _predict_joint_proba(self, X):
        '''
        Method for calculating and returning the joint probability. 

        Parameters
        ----------
        X : 2D numpy array
            2D numpy array representing input data, where X[n, i] represents the i-th element of n-th point in X.

        Returns
        ----------
        joint_proba : 2D numpy array
            A numpy array with shape (len(X), self.K), where joint_proba[n, k] = joint probability p(X[n], z_k=1 | training data)
        '''
        L = np.reshape( (self.nu + 1 - self.D)*self.beta/(1 + self.beta), (self.K, 1,1) ) * self.W
        tmp = np.zeros((len(X), self.K))
        for k in range(self.K):
            tmp[:,k] = multi_student_t(X, self.m[k], L[k], self.nu[k] + 1 - self.D)
        return tmp * np.reshape(self.alpha/(self.alpha.sum()), (1, self.K))

    def calc_prob_density(self, X):
        '''
        Method for calculating and returning the predictive density.

        Parameters
        ----------
        X : 2D numpy array
            2D numpy array representing input data, where X[n, i] represents the i-th element of n-th point in X.

        Returns
        ----------
        prob_density : 1D numpy array
            A numpy array with shape (len(X), ), where proba[n] =  p(X[n] | training data)
        '''
        joint_proba = self._predict_joint_proba(X)
        return joint_proba.sum(axis=1)

    def predict_proba(self, data):
        '''
        Method for calculating and returning the probability of belonging to each component.

        Parameters
        ----------
        X : 2D numpy array
            2D numpy array representing input data, where X[n, i] represents the i-th element of n-th point in X.

        Returns
        ----------
        proba : 2D numpy array
            A numpy array with shape (len(X), self.K), where proba[n, k] =  p(z_k=1 | X[n], training data)
        '''
        if isinstance(data, xr.Dataset):
            X = data.X.values
            if len(X.shape) == 1:
                X= X.reshape(1, -1)
        else:
            X = data
        joint_proba = self._predict_joint_proba(X)
        return joint_proba / joint_proba.sum(axis=1).reshape(-1, 1)

    def predict(self, X):
        '''
        Method for predicting which component each input data belongs to.

        Parameters
        ----------
        X : 2D numpy array
            2D numpy array representing input data, where X[n, i] represents the i-th element of n-th point in X.

        Returns
        ----------
        pred : 1D numpy array
            A numpy array with shape (len(X), ), where pred[n] =  argmax_{k} p(z_k=1 | X[n], training data)
        '''
        proba = self.predict_proba(X)
        return proba.argmax(axis=1)
    
    def generate(self, n_samples):
        '''
        Method for generating new data points based on the estimated model parameters.

        Parameters
        ----------
        n_samples : int
            The number of samples to be generated.

        Returns
        ----------
        data : dict
            A dictionary containing the generated data, where data['X'] is the generated data.
        '''
        if self.c_alpha is None:
            alpha_norm = self.alpha / self.alpha.sum()
            z_new = np.random.multinomial(1, alpha_norm, size=n_samples)
        else:
            if self.mixture_pi:
                comopnent_idx = np.random.choice(self.comopnent_num, size=n_samples, p=self.pi_mixture_ratio)
                z_new = []
                for i in range(n_samples):
                    alpha_norm = self.c_alpha[comopnent_idx[i]]/np.sum(self.c_alpha[comopnent_idx[i]])
                    z_new.append(np.random.multinomial(1, alpha_norm, size=1))
                z_new = np.vstack(z_new)
            else:
               alpha_norm = self.c_alpha/np.sum(self.c_alpha)
               z_new = np.random.multinomial(1, alpha_norm, size=n_samples)
        X_new = np.zeros((n_samples, self.D))
        
        for k in range(self.K):
            idx = np.where(z_new[:, k] == 1)[0]
            if len(idx) > 0:
                X_new[idx] = np.random.multivariate_normal(
                    self.m[k], 
                    np.linalg.inv(self.beta[k] * self.W[k]),
                    size=len(idx)
                )
        
        ret_ds = xr.Dataset(
            {
                'X': (['n', 'd'], X_new),
            },
            coords={'n': np.arange(n_samples), 'd': np.arange(self.D)}
        )
        return ret_ds


class BayesianGaussianMixtureModelWithContext(BayesianGaussianMixtureModel):
    def __init__(self, K, D, alpha0, beta0, nu0, m0, W0, c_alpha, pi_mixture_ratio=None):
        super().__init__(K, D, alpha0, beta0, nu0, m0, W0, c_alpha, pi_mixture_ratio)
        self.C = None
        self.Z = None

    def fit(self, data, max_iter=1e3, tol=1e-4, random_state=None, disp_message=False):
        '''
        Method for fitting the model.

        Parameters
        ----------
        X : 2D numpy array
            2D numpy array representing input data, where X[n, i] represents the i-th element of n-th point in X.
        C : 2D numpy array
            2D numpy array representing context data, where C[n, k] represents the k-th element of n-th point in C.
        max_iter : int
            The maximum number of iteration
        tol : float
            The criterion for juding the convergence. 
            When the change of lower bound becomes smaller than tol, the iteration is stopped.
        random_state : int
            An integer specifying the random number seed for random initialization
        disp_message : Boolean
            Whether to show the message on the result.
        '''
        if self.X is None and self.C is None:
            self.X = data.X.values
            self.C = data.C.values
            self.Z = data.Z.values
            if len(self.X.shape) == 1:
                self.X, self.C, self.Z = self.X.reshape(1, -1), self.C.reshape(1, -1), self.Z.reshape(1, -1)
            self._init_params(self.X, random_state=random_state)
        elif self.X is not None and self.C is not None:
            self.X = np.vstack([self.X, data.X.values])
            self.C = np.vstack([self.C, data.C.values])
            self.Z = np.vstack([self.Z, data.Z.values])


        r = self._e_like_step(self.X, self.C)
        lower_bound = self._calc_lower_bound(r)

        for i in range(max_iter):
            self._m_like_step(self.X, r)
            r = self._e_like_step(self.X, self.C)

            lower_bound_prev = lower_bound
            lower_bound = self._calc_lower_bound(r)

            if abs(lower_bound - lower_bound_prev) < tol:
                break

        self.lower_bound = lower_bound
        # for i in range(len(self.X)):
        #     print('x:',self.X[i])
        #     print('c:',self.C[i])
        #     print('z:',self.Z[i])
        #     print('---------')

        if disp_message:
            print(f"n_iter : {i}")
            print(f"convergend : {i < max_iter}")
            print(f"lower bound : {lower_bound}")
            print(f"Change in the variational lower bound : {lower_bound - lower_bound_prev}")
    def _e_like_step(self, X, C):
        '''
        Method for calculating the array corresponding to responsibility.

        Parameters
        ----------
        X : 2D numpy array
            2D numpy array representing input data, where X[n, i] represents the i-th element of n-th point in X.
        C : 2D numpy array
            2D numpy array representing context data, where C[n, k] represents the k-th element of n-th point in C.
        Returns
        ----------
        r : 2D numpy array
            2D numpy array representing responsibility of each component for each sample in X, 
            where r[n, k] = $r_{n, k}$.

        '''
        N, _ = np.shape(X)

        tpi = self.C

        arg_digamma = np.reshape(self.nu, (self.K, 1)) - np.reshape(np.arange(0, self.D, 1), (1, self.D))
        tlam = np.exp( digamma(arg_digamma/2).sum(axis=1)  + self.D * np.log(2) + np.log(np.linalg.det(self.W)) )

        diff = np.reshape(X, (N, 1, self.D) ) - np.reshape(self.m, (1, self.K, self.D) )
        exponent = self.D / self.beta + self.nu * np.einsum("nkj,nkj->nk", np.einsum("nki,kij->nkj", diff, self.W), diff)

        exponent_subtracted = exponent - np.reshape(exponent.min(axis=1), (N, 1))
        rho = tpi*np.sqrt(tlam)*np.exp( -0.5 * exponent_subtracted )
        r = rho/np.reshape(rho.sum(axis=1), (N, 1))


        return r
    def _m_like_step(self, X, r):
        '''
        Method for calculating the model parameters based on the responsibility.

        Parameters
        ----------
        X : 2D numpy array
            2D numpy array representing input data, where X[n, i] represents the i-th element of n-th point in X.
        r : 2D numpy array
            2-D numpy array representing responsibility of each component for each sample in X, 
            where r[n, k] = $r_{n, k}$.
        '''
        N, _ = np.shape(X)
        n_samples_in_component = r.sum(axis=0)
        barx = r.T @ X / np.reshape(n_samples_in_component, (self.K, 1))
        diff = np.reshape(X, (N, 1, self.D) ) - np.reshape(barx, (1, self.K, self.D) )
        S = np.einsum("nki,nkj->kij", np.einsum("nk,nki->nki", r, diff), diff) / np.reshape(n_samples_in_component, (self.K, 1, 1))

        self.alpha = self.alpha0 + n_samples_in_component
        self.beta = self.beta0 + n_samples_in_component
        self.nu = self.nu0 + n_samples_in_component
        self.m = (self.m0 * self.beta0 + barx * np.reshape(n_samples_in_component, (self.K, 1)))/np.reshape(self.beta, (self.K, 1))

        diff2 = barx - self.m0
        Winv = np.reshape(np.linalg.inv( self.W0 ), (1, self.D, self.D)) + \
            S * np.reshape(n_samples_in_component, (self.K, 1, 1)) + \
            np.reshape( self.beta0 * n_samples_in_component / (self.beta0 + n_samples_in_component), (self.K, 1, 1)) * np.einsum("ki,kj->kij",diff2,diff2) 
        self.W = np.linalg.inv(Winv)
    def generate(self, n_samples):
        '''
        Method for generating new data points based on the estimated model parameters.

        Parameters
        ----------
        n_samples : int
            The number of samples to be generated.

        Returns
        ----------
        X_new : 2D numpy array
            A numpy array with shape (n_samples, self.D), where X_new[n] is the n-th generated sample.
        C_new : 1D numpy array
            A numpy array with shape (n_samples, ), where C_new[n] is the context of the n-th generated sample.
        '''
        if self.c_alpha is None:
            alpha_norm = self.alpha / self.alpha.sum()
            z_new = np.random.multinomial(1, alpha_norm, size=n_samples)
            C_new = np.random.dirichlet(self.c_alpha, size=n_samples)
        else:
            if self.mixture_pi:
                comopnent_idx = np.random.choice(self.comopnent_num, size=n_samples, p=self.pi_mixture_ratio)
                z_new = []
                C_new = []
                for i in range(n_samples):
                    C_new_temp = np.random.dirichlet(self.c_alpha[comopnent_idx[i]], size=1)[0]
                    C_new.append(C_new_temp)
                    z_new.append(np.random.multinomial(1, C_new_temp, size=1))
                z_new = np.vstack(z_new)
                C_new = np.vstack(C_new)
                # for i in range(n_samples):
                #     print(z_new[i], C_new[i],comopnent_idx[i])
            else:
                C_new_temp = np.random.dirichlet(self.c_alpha, size=n_samples)
                z_new = np.array([np.random.multinomial(1, C_new_temp[i], size=1)[0] for i in range(n_samples)])
                C_new = C_new_temp
        X_new = np.zeros((n_samples, self.D))
        for k in range(self.K):
            idx = np.where(z_new[:, k] == 1)[0]
            if len(idx) > 0:
                X_new[idx] = np.random.multivariate_normal(
                    self.m[k], 
                    np.linalg.inv(self.beta[k] * self.W[k]),
                    size=len(idx)
                )
            # print('z:',z_new)
            # print('idx:',idx)
            # print('X:',X_new)
        ret_ds = xr.Dataset(
            {
                'X': (['n', 'd'], X_new),
                'C': (['n', 'k'], C_new),
                'Z': (['n', 'k'], z_new),
            },
            coords={'n': np.arange(n_samples), 'd': np.arange(self.D), 'k': np.arange(self.K)}
        )
        return ret_ds                                                                               
    
    def predict_proba(self, data):
        '''
        Method for calculating and returning the probability of belonging to each component.

        Parameters
        ----------
        data : 2D numpy array or tuple of 2D numpy arrays
            If data is a 2D numpy array, it represents input data X, where X[n, i] represents the i-th element of n-th point in X.
            If data is a tuple of 2D numpy arrays (X, C), X[n, i] represents the i-th element of n-th point in X, and C[n, k] represents the k-th element of context for n-th point in X.

        Returns
        ----------
        proba : 2D numpy array
            A numpy array with shape (len(X), self.K), where proba[n, k] =  p(z_k=1 | X[n], C[n], training data)
        '''
        if isinstance(data, tuple):
            X, C = data
        elif isinstance(data, xr.Dataset):
            X = data.X.values
            C = data.C.values
            if len(X.shape) == 1:
                X, C = X.reshape(1, -1), C.reshape(1, -1)
        else:
            X = data
        joint_proba = self._predict_joint_proba(X, C)
        return joint_proba / joint_proba.sum(axis=1).reshape(-1, 1)
    def _predict_joint_proba(self, X, C):
        '''
        Method for calculating and returning the joint probability.     

        Parameters
        ----------
        X : 2D numpy array
            2D numpy array representing input data, where X[n, i] represents the i-th element of n-th point in X.
        C : 2D numpy array
            2D numpy array representing context data, where C[n, k] represents the k-th element of n-th point in C.

        Returns
        ----------
        joint_proba : 2D numpy array
            A numpy array with shape (len(X), self.K), where joint_proba[n, k] = joint probability p(X[n], z_k=1 | training data)
        '''
        L = np.reshape( (self.nu + 1 - self.D)*self.beta/(1 + self.beta), (self.K, 1,1) ) * self.W
        tmp = np.zeros((len(X), self.K))
        for k in range(self.K):
            tmp[:,k] = multi_student_t(X, self.m[k], L[k], self.nu[k] + 1 - self.D)
        return tmp * C