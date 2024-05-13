from pycox_local.pycox.datasets import kkbox,support,metabric,gbsg,flchain
from torch.utils.data.dataset import Dataset
from torch.utils.data.dataloader import DataLoader
from pycox_local.pycox.preprocessing.feature_transforms import *
import torch
from .toy_data_generation import toy_data_class
from sklearn.preprocessing import MinMaxScaler,StandardScaler
from sklearn_pandas import DataFrameMapper
from sklearn.model_selection import train_test_split
from sklearn.model_selection import StratifiedKFold
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from lifelines import KaplanMeierFitter
import pycox_local.pycox.utils as utils

def calc_km(durations,events):
    km = utils.kaplan_meier(durations, 1 - events)
    return km

class LogTransformer(BaseEstimator, TransformerMixin): #Scaling is already good. This leaves network architecture...
    def __init__(self):
        pass

    def fit_transform(self, input_array, y=None):
        return np.log(input_array)

    def fit(self, input_array, y=None):
        return self

    def transform(self, input_array, y=None):
        return np.log(input_array)

    def inverse_transform(self,input_array):
        return np.exp(input_array)

class IdentityTransformer(BaseEstimator, TransformerMixin): #Scaling is already good. This leaves network architecture...
    def __init__(self):
        pass

    def fit_transform(self, input_array, y=None):
        return input_array

    def fit(self, input_array, y=None):
        return self

    def transform(self, input_array, y=None):
        return input_array

    def inverse_transform(self,input_array):
        return input_array

pd.set_option('display.max_rows', 500)
pd.set_option('display.max_columns', 500)
pd.set_option('display.width', 1000)


class survival_dataset(Dataset):
    def __init__(self,str_identifier,seed=1337,fold_idx=0,sumo_net=True):
        print('fold_idx: ', fold_idx)
        super(survival_dataset, self).__init__()
        if str_identifier=='support':
            data = support
            cont_cols = ['x0','x3','x7','x8','x9','x10','x11','x12','x13']
            binary_cols = ['x1','x4','x5']
            cat_cols = ['x2','x6']

        elif str_identifier=='metabric':
            data = metabric
            cont_cols = ['x0', 'x1', 'x2', 'x3', 'x8']
            binary_cols = ['x4', 'x5', 'x6', 'x7']
            cat_cols = []

        elif str_identifier=='gbsg':
            data = gbsg
            cont_cols = ['x3','x4','x5','x6']
            binary_cols = ['x0', 'x2']
            cat_cols = ['x1']
        elif str_identifier == 'flchain':
            data = flchain
            cont_cols = ['sample.yr','age','kappa','lambda','creatinine']
            binary_cols = ['sex','mgus']
            cat_cols = ['flc.grp']
        elif str_identifier=='kkbox':
            data = kkbox
            cont_cols = ['n_prev_churns','log_days_between_subs','log_days_since_reg_init','log_payment_plan_days','log_plan_list_price','log_actual_amount_paid','age_at_start']
            binary_cols = ['is_auto_renew','is_cancel','strange_age','nan_days_since_reg_init','no_prev_churns']
            cat_cols = ['city','payment_method_id','gender','registered_via']
        elif str_identifier=='weibull':
            data = toy_data_class(str_identifier)
            cont_cols = ['x1']
            binary_cols = []
            cat_cols = []
        elif str_identifier=='checkboard':
            data = toy_data_class(str_identifier)
            cont_cols = ['x1']
            binary_cols = []
            cat_cols = []
        elif str_identifier=='normal':
            data = toy_data_class(str_identifier)
            cont_cols = ['x1']
            binary_cols = []
            cat_cols = []
        df_full = data.read_df()
        df_full = df_full.dropna()

        if str_identifier=='kkbox':
            self.event_col = 'event'
            self.duration_col = 'duration'
            df_full = df_full.drop(['msno'],axis=1)
        else:
            self.event_col = data.col_event
            self.duration_col = data.col_duration
        
        # print("\nHazardous debug\n")
        # from hazardous.data._competing_weibull import make_synthetic_competing_weibull
        
        # df_full, y = make_synthetic_competing_weibull(
        #     n_events=1,
        #     n_samples=100_000,
        #     n_features=20,
        #     complex_features=True,
        #     return_X_y=True,
        # )
        # df_full = pd.concat([df_full, y], axis=1)
        # print(f"Hazardous debug: {df_full.shape}")
        # self.event_col = "event"
        # self.duration_col = "duration"
        # cat_cols = []
        # cont_cols = df_full.columns.to_list()
        # binary_cols = []

        print(f'{str_identifier} max',df_full[self.duration_col].max())
        print(f'{str_identifier} min',df_full[self.duration_col].min())
        c = OrderedCategoricalLong()
        for el in cat_cols:
            df_full[el] = c.fit_transform(df_full[el])
        if sumo_net:
            standardize = [([col], MinMaxScaler()) for col in cont_cols]
            self.duration_mapper = MinMaxScaler()
        else:
            standardize = [([col], StandardScaler()) for col in cont_cols]
            self.duration_mapper = StandardScaler()
        self.duration_mapper_2 = MinMaxScaler()
        leave = [(col,None) for col in binary_cols]
        self.cat_cols = cat_cols
        self.x_mapper = DataFrameMapper(standardize+leave)
        if self.cat_cols:
            self.unique_cat_cols = df_full[cat_cols].max(axis=0).tolist()
            self.unique_cat_cols = [el+1 for el in self.unique_cat_cols]
            # for el in cat_cols:
            #     print(f'column {el}:', df_full[el].unique().tolist())
            # print(self.unique_cat_cols)
        else:
            self.unique_cat_cols = []

        folder = StratifiedKFold(n_splits=5,  shuffle=True, random_state=seed)
        splits = list(folder.split(df_full,df_full[self.event_col]))
        tr_idx,tst_idx = splits[fold_idx]
        df_train = df_full.iloc[tr_idx,:]
        df_test = df_full.iloc[tst_idx,:]
        df_train, df_val, _, _ = train_test_split(df_train, df_train[self.event_col], test_size = 0.25,stratify=df_train[self.event_col])

        x_train = self.x_mapper.fit_transform(df_train[cont_cols+binary_cols]).astype('float32')
        x_val = self.x_mapper.transform(df_val[cont_cols+binary_cols]).astype('float32')
        x_test = self.x_mapper.transform(df_test[cont_cols+binary_cols]).astype('float32')

        y_train = self.duration_mapper.fit_transform(df_train[self.duration_col].values.reshape(-1,1)).astype('float32')
        y_val = self.duration_mapper.transform(df_val[self.duration_col].values.reshape(-1,1)).astype('float32')
        y_test = self.duration_mapper.transform(df_test[self.duration_col].values.reshape(-1,1)).astype('float32')

        self.y_train_ref = self.duration_mapper_2.fit_transform(df_train[self.duration_col].values.reshape(-1,1)).astype('float32')
        self.y_val_ref = self.duration_mapper_2.transform(df_val[self.duration_col].values.reshape(-1,1)).astype('float32')
        self.y_test_ref = self.duration_mapper_2.transform(df_test[self.duration_col].values.reshape(-1,1)).astype('float32')


        self.split(X=x_train,delta=df_train[self.event_col],y=y_train,mode='train',cat=cat_cols,df=df_train)
        self.split(X=x_val,delta=df_val[self.event_col],y=y_val,mode='val',cat=cat_cols,df=df_val)
        self.split(X=x_test,delta=df_test[self.event_col],y=y_test,mode='test',cat=cat_cols,df=df_test)
        self.set('train')


    def split(self,X,delta,y,cat=[],mode='train',df=[]):
        min_dur,max_dur = y.min(),y.max()
        times = np.linspace(min_dur,max_dur,100)
        d = delta.values
        kmf = KaplanMeierFitter()
        kmf.fit(y,1-delta)
        setattr(self,f'{mode}_times', torch.from_numpy(times.astype('float32')).float().unsqueeze(-1))
        setattr(self,f'{mode}_delta', torch.from_numpy(delta.astype('float32').values).float())
        setattr(self,f'{mode}_y', torch.from_numpy(y).float())
        setattr(self, f'{mode}_X', torch.from_numpy(X).float())
        if self.cat_cols:
            setattr(self, f'{mode}_cat_X', torch.from_numpy(df[cat].astype('int64').values).long())

    def set(self,mode='train'):
        self.X = getattr(self,f'{mode}_X')
        self.y = getattr(self,f'{mode}_y')
        self.times = getattr(self,f'{mode}_times')
        self.delta = getattr(self,f'{mode}_delta')
        if self.cat_cols:
            self.cat_X = getattr(self,f'{mode}_cat_X')
        else:
            self.cat_X = []
        self.min_duration = self.y.min().numpy()
        self.max_duration = self.y.max().numpy()

    def transform_x(self,x):
        return self.x_mapper.transform(x)

    def invert_duration(self,duration):
        return self.duration_mapper.inverse_transform(duration)

    def transform_duration(self,duration):
        return self.duration_mapper.transform(duration)

    def __getitem__(self, index):
        if self.cat_cols:
            return self.X[index,:],self.cat_X[index,:],self.y[index],self.delta[index]
        else:
            return self.X[index,:],self.cat_X,self.y[index],self.delta[index]

    def __len__(self):
        return self.X.shape[0]

class chunk_iterator():
    def __init__(self,X,delta,y,cat_X,shuffle,batch_size):
        self.X = X
        self.delta = delta
        self.y = y
        self.cat_X = cat_X
        self.shuffle = shuffle
        self.batch_size = batch_size
        self.n = self.X.shape[0]
        self.chunks=self.n//batch_size+1
        self.perm = torch.randperm(self.n)
        self.valid_cat = not isinstance(self.cat_X, list)
        if self.shuffle:
            self.X = self.X[self.perm,:]
            self.delta = self.delta[self.perm]
            self.y = self.y[self.perm,:]
            if self.valid_cat: #F
                self.cat_X = self.cat_X[self.perm,:]
        self._index = 0
        self.it_X = torch.chunk(self.X,self.chunks)
        self.it_delta = torch.chunk(self.delta,self.chunks)
        self.it_y = torch.chunk(self.y,self.chunks)
        if self.valid_cat:  # F
            self.it_cat_X = torch.chunk(self.cat_X,self.chunks)
        else:
            self.it_cat_X = []
        self.true_chunks = len(self.it_X)

    def __next__(self):
        ''''Returns the next value from team object's lists '''
        if self._index < self.true_chunks:
            if self.valid_cat:
                result = (self.it_X[self._index],self.it_cat_X[self._index],self.it_y[self._index],self.it_delta[self._index])
            else:
                result = (self.it_X[self._index],[],self.it_y[self._index],self.it_delta[self._index])
            self._index += 1
            return result
        # End of Iteration
        raise StopIteration

    def __len__(self):
        return len(self.it_X)

class custom_dataloader():
    def __init__(self,dataset,batch_size=32,shuffle=False):
        self.dataset = dataset
        self.batch_size = batch_size
        self.shuffle = shuffle
        self.n = self.dataset.X.shape[0]
        self.len=self.n//batch_size+1
    def __iter__(self):
        return chunk_iterator(X =self.dataset.X,
                              delta = self.dataset.delta,
                              y = self.dataset.y,
                              cat_X = self.dataset.cat_X,
                              shuffle = self.shuffle,
                              batch_size=self.batch_size,
                              )
    def __len__(self):
        self.n = self.dataset.X.shape[0]
        self.len = self.n // self.batch_size + 1
        return self.len

def get_dataloader(str_identifier,bs,seed,fold_idx,shuffle=True,sumo_net=False):
    d = survival_dataset(str_identifier, seed, fold_idx=fold_idx, sumo_net=sumo_net)
    dat = custom_dataloader(dataset=d,batch_size=bs,shuffle=shuffle)
    return dat
