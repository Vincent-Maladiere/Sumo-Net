import pycox
import matplotlib.pyplot as plt
import torch
import numpy as np

class HazardLikelihoodCoxTime():
    def __init__(self,pycox_model):
        self.model = pycox_model
        base_haz = self.model.compute_baseline_hazards()
        self.base_haz_time,self.base_haz = torch.from_numpy(base_haz.index.values).float(), torch.from_numpy(base_haz.values).float()
        self.min_base_haz_time = self.base_haz_time.min()
        self.max_base_haz_time = self.base_haz_time.max()

    def check_min(self,t,haz_vec):
        haz_vec[t<self.min_base_haz_time] = self.base_haz[0]
        return haz_vec

    def check_max(self,t,haz_vec):
        haz_vec[t>self.max_base_haz_time] = self.base_haz[-1]
        return haz_vec

    def get_base(self,t):
        bool_mask = t<=self.base_haz_time
        idx = torch.arange(bool_mask.shape[1], 0, -1)
        tmp2 = bool_mask * idx
        indices = torch.argmax(tmp2, 1, keepdim=True)
        base_ind = indices-1
        b = self.base_haz[base_ind]
        dist_t = t-self.base_haz_time[base_ind]
        dist = self.base_haz_time[indices]-self.base_haz_time[base_ind]
        delta = (self.base_haz[indices]-self.base_haz[base_ind])/dist
        haz_vec = b+delta*dist_t
        return haz_vec

    def get_vec_base(self,t):
        bool_mask = t>=self.base_haz_time
        tmp2 = bool_mask * self.base_haz #Might have to refine this step later
        return tmp2

    def get_base_haz_interpolate(self,t):
        haz_vec = self.get_base(t)
        haz_vec = self.check_min(t,haz_vec)
        haz_vec = self.check_max(t,haz_vec)
        return haz_vec

    def calculate_hazard(self,X,T,event):
        event = event.bool().squeeze()
        X = X[event,:]
        T=T[event]
        chks = X.shape[0]//5000 + 1
        haz_list = []
        for x,t in zip(torch.chunk(X,chks,dim=0),torch.chunk(T,chks,dim=0)):
            base_haz = self.get_base_haz_interpolate(t)
            exp_g = self.model.predict((x,t)).exp().cpu()
            haz_list.append(exp_g*base_haz)
        hazard = torch.cat(haz_list,dim=0)
        return hazard

    def calculate_cumulative_hazard(self,X,T):
        chks = X.shape[0]//5000 + 1
        c_haz_list = []
        for x,t in zip(torch.chunk(X,chks,dim=0),torch.chunk(T,chks,dim=0)):
            vec_hazard = self.get_vec_base(t)
            new_x = x.repeat_interleave(self.base_haz_time.shape[0],dim=0)
            new_t = self.base_haz_time.repeat(x.shape[0]).unsqueeze(-1)
            exp_g = self.model.predict((new_x,new_t)).view(x.shape[0],-1).exp().cpu()
            cum_hazard = torch.sum(vec_hazard*exp_g,dim=1)
            c_haz_list.append(cum_hazard)
        cum_hazard = torch.cat(c_haz_list,dim=0)
        return cum_hazard

    def estimate_likelihood(self,X,T,event):
        if T.dim()!=2:
            T = T.unsqueeze(-1)
        assert T.dim()==2
        haz = self.calculate_hazard(X,T,event)
        cum_haz = self.calculate_cumulative_hazard(X,T)
        L = self.calc_likelihood(hazard=haz,cum_hazard=cum_haz)
        return L

    def calc_likelihood(self,hazard,cum_hazard):
        n =cum_hazard.shape[0]
        return -((hazard + 1e-6).log().sum() - cum_hazard.sum())/n

class general_likelihood():
    def __init__(self,pycox_model):
        self.model = pycox_model

    def get_S_and_f(self, X, T, event):
        event = event.bool()
        chks = X.shape[0]//5000 + 1
        S_cat = []
        f_cat = []
        for x,t in zip(torch.chunk(X,chks,dim=0),torch.chunk(T,chks,dim=0)):
            surv_df = self.model.predict_surv_df(x)
            times = torch.from_numpy(surv_df.index.values).float()
            surv_tensor = torch.from_numpy(surv_df.values).t().float()
            min_time = times.min().item()
            min_bool = (t < min_time).squeeze()
            max_time = times.max().item()
            max_bool = (t > max_time).squeeze()
            bool_mask = t <= times
            idx = torch.arange(bool_mask.shape[1], 0, -1)
            tmp2 = bool_mask * idx
            indices = torch.argmax(tmp2, 1, keepdim=True)
            base_ind = torch.relu(indices-1)
            S_t_1 = torch.gather(surv_tensor,dim=1,index=indices)
            S_t_0 = torch.gather(surv_tensor,dim=1,index=base_ind)
            delta  = times[indices]-times[base_ind]
            t_prime = t - times[base_ind]
            S = (1-t_prime/delta)*S_t_0+t_prime/delta*S_t_1
            f = -(S_t_1-S_t_0)/delta
            f[min_bool]=0.0
            f[max_bool]=0.0
            S[min_bool]= surv_tensor[min_bool,0].unsqueeze(-1)
            S[max_bool]= surv_tensor[max_bool,-1].unsqueeze(-1)
            S_cat.append(S)
            f_cat.append(f)
        S_cat = torch.cat(S_cat,dim=0)
        f_cat = torch.cat(f_cat,dim=0)
        assert S_cat.shape[0]==event.shape[0]
        assert f_cat.shape[0]==event.shape[0]
        return S_cat[~event],f_cat[event]

    def estimate_likelihood(self,X,T,event):
        if T.dim()!=2:
            T = T.unsqueeze(-1)
        assert T.dim()==2
        S,f = self.get_S_and_f(X,T,event)
        L = self.calc_likelihood(S,f)
        return L

    def calc_likelihood(self,S, f):
        n = S.shape[0]+f.shape[0]
        return -((f + 1e-6).log().sum() + S.sum())/n

# if __name__ == '__main__':
#     import numpy as np
#     from sklearn.preprocessing import StandardScaler
#     from sklearn_pandas import DataFrameMapper
#     import torch
#     import torchtuples as tt
#
#     from pycox.datasets import metabric
#     from pycox.models import CoxCC, CoxPH, CoxTime
#     from pycox.evaluation import EvalSurv
#     from pycox.models.cox_time import MLPVanillaCoxTime
#
#     np.random.seed(1234)
#     _ = torch.manual_seed(123)
#
#     df_train = metabric.read_df()
#     df_test = df_train.sample(frac=0.2)
#     df_train = df_train.drop(df_test.index)
#     df_val = df_train.sample(frac=0.25)
#     df_train = df_train.drop(df_val.index)
#
#     cols_standardize = ['x0', 'x1', 'x2', 'x3', 'x8']
#     cols_leave = ['x4', 'x5', 'x6', 'x7']
#
#     standardize = [([col], StandardScaler()) for col in cols_standardize]
#     leave = [(col, None) for col in cols_leave]
#
#     x_mapper = DataFrameMapper(standardize + leave)
#
#     x_train = x_mapper.fit_transform(df_train).astype('float32')
#     x_val = x_mapper.transform(df_val).astype('float32')
#     x_test = x_mapper.transform(df_test).astype('float32')
#
#     labtrans = CoxTime.label_transform()
#     get_target = lambda df: (df['duration'].values, df['event'].values)
#     y_train = labtrans.fit_transform(*get_target(df_train))
#     y_val = labtrans.transform(*get_target(df_val))
#     durations_test, events_test = get_target(df_test)
#     val = tt.tuplefy(x_val, y_val)
#
#     in_features = x_train.shape[1]
#     num_nodes = [32, 32]
#     out_features = 1
#     batch_norm = True
#     dropout = 0.1
#     output_bias = False
#
#     # net = tt.practical.MLPVanilla(in_features, num_nodes, out_features, batch_norm,
#     #                               dropout, output_bias=output_bias)
#     net = MLPVanillaCoxTime(in_features, num_nodes, batch_norm, dropout)  # Actual net to be used
#     model = CoxTime(net, tt.optim.Adam)  # the cox time framework, dont do this..
#     model.optimizer.set_lr(0.01)
#     epochs = 512
#     callbacks = [tt.callbacks.EarlyStopping()]
#     verbose = True
#     batch_size = 256
#     print(x_train.shape)
#     log = model.fit(x_train, y_train, batch_size, epochs, callbacks, verbose,
#                     val_data=val.repeat(10).cat())
#     base_haz = model.compute_baseline_hazards()
#     cum_base_haz = model.compute_baseline_cumulative_hazards()
#     t,s = torch.from_numpy(base_haz.index.values),torch.from_numpy(base_haz.values)
#     reference_t = torch.tensor([[-100.0],[1.5],[200.0]])
#     survL = general_likelihood(model)
#     L_S = survL.estimate_likelihood(torch.from_numpy(x_val),(torch.from_numpy(y_val[0]).unsqueeze(-1),torch.from_numpy(y_val[1])))
#     print(L_S)
#     coxL = HazardLikelihoodCoxTime(model)
#     L = coxL.estimate_likelihood(torch.from_numpy(x_val),(torch.from_numpy(y_val[0]).unsqueeze(-1),torch.from_numpy(y_val[1])))
#     print(L)
    # surv_base = np.exp(-model.compute_baseline_cumulative_hazards())
    # surv_base.plot()
    # plt.savefig('test.png')
    # surv = model.predict_surv_df(x_test)
    # ev = EvalSurv(surv, durations_test, events_test, censor_surv='km')
    # conc = ev.concordance_td()
    # time_grid = np.linspace(durations_test.min(), durations_test.max(), 100)
    # ibs = ev.integrated_brier_score(time_grid)
    # inll = ev.integrated_nbll(time_grid)
