import torch

class Log1PlusExp(torch.autograd.Function):
    """Implementation of x ↦ log(1 + exp(x))."""
    @staticmethod
    def forward(ctx, x):
        exp = x.exp()
        ctx.save_for_backward(x)
        y = exp.log1p()
        return x.where(torch.isinf(exp),y.half() if x.type()=='torch.cuda.HalfTensor' else y )

    @staticmethod
    def backward(ctx, grad_output):
        x, = ctx.saved_tensors
        y = (-x).exp().half() if x.type()=='torch.cuda.HalfTensor' else (-x).exp()
        return grad_output / (1 + y)

class Swish(torch.autograd.Function):
    @staticmethod
    def forward(ctx, i):
        result = i * torch.sigmoid(i)
        ctx.save_for_backward(i)
        return result

    @staticmethod
    def backward(ctx, grad_output):
        i = ctx.saved_variables[0]
        sigmoid_i = torch.sigmoid(i)
        return grad_output * (sigmoid_i * (1 + i * (1 - sigmoid_i)))

class CustomSwish(torch.nn.Module):
    def forward(self, input_tensor):
        return Swish.apply(input_tensor)

class multi_input_Sequential(torch.nn.Sequential):
    def forward(self, inputs):
        for module in self._modules.values():
            if type(inputs) == tuple:
                inputs = module(*inputs)
            else:
                inputs = module(inputs)
        return inputs

class multi_input_Sequential_res_net(torch.nn.Sequential):
    def forward(self, inputs):
        for module in self._modules.values():
            if type(inputs) == tuple:
                inputs = module(*inputs)
            else:
                output = module(inputs)
                if inputs.shape[1]==output.shape[1]:
                    inputs = inputs+output
                else:
                    inputs = output
        return inputs

log1plusexp = Log1PlusExp.apply
class nn_node(torch.nn.Module): #Add dropout layers, Do embedding layer as well!
    def __init__(self,d_in,d_out,cat_size_list,dropout=0.1,transformation=torch.tanh):
        super(nn_node, self).__init__()

        self.has_cat = len(cat_size_list)>0
        self.latent_col_list = []
        print('cat_size_list',cat_size_list)
        for i,el in enumerate(cat_size_list):
            col_size = el//2+2
            setattr(self,f'embedding_{i}',torch.nn.Embedding(el,col_size))
            self.latent_col_list.append(col_size)
        self.w = torch.nn.Linear(d_in+sum(self.latent_col_list),d_out)
        self.f = transformation
        self.dropout = torch.nn.Dropout(dropout)

    def forward(self,X,x_cat=[]):
        if not isinstance(x_cat,list):
            seq = torch.unbind(x_cat,1)
            cat_vals = [X]
            for i,f in enumerate(seq):
                o = getattr(self,f'embedding_{i}')(f)
                cat_vals.append(o)
            X = torch.cat(cat_vals,dim=1)
        return self.dropout(self.f(self.w(X)))

class bounded_nn_layer(torch.nn.Module): #Add dropout layers
    def __init__(self, d_in, d_out, bounding_op=lambda x: x ** 2, transformation=torch.tanh):
        super(bounded_nn_layer, self).__init__()
        self.W = torch.nn.Parameter(torch.randn(*(d_in,d_out)),requires_grad=True)
        self.f = transformation
        self.bounding_op = bounding_op
        self.bias = torch.nn.Parameter(torch.randn(d_out),requires_grad=True)

    def forward(self,X):
        return self.f(X@self.bounding_op(self.W)+self.bias)

class bounded_nn_layer_last(torch.nn.Module):  # Add dropout layers
    def __init__(self, d_in, d_out, bounding_op=lambda x: x ** 2, transformation=torch.tanh):
        super(bounded_nn_layer_last, self).__init__()
        self.W = torch.nn.Parameter(torch.randn(*(d_in, d_out)), requires_grad=True)
        self.f = transformation
        self.bounding_op = bounding_op
        self.bias = torch.nn.Parameter(torch.randn(d_out), requires_grad=True)

    def forward(self, X):
        return X @ self.bounding_op(self.W) + self.bias

class mixed_layer(torch.nn.Module): #Add dropout layers
    def __init__(self, d_in, d_in_bounded, d_out, bounding_op=lambda x: x ** 2, transformation=torch.tanh):
        super(mixed_layer, self).__init__()
        self.pos_weights = torch.nn.Parameter(torch.randn(*(d_in_bounded, d_out)), requires_grad=True)
        self.f = transformation
        self.bounding_op = bounding_op
        self.bias = torch.nn.Parameter(torch.randn(d_out), requires_grad=True)
        self.w = torch.nn.Linear(d_in,d_out)

    def forward(self,X,x_bounded):
        return self.f(x_bounded @ self.bounding_op(self.pos_weights) + self.bias + self.w(X))

class mixed_layer_all(torch.nn.Module): #Add dropout layers
    def __init__(self, d_in, d_in_bounded,cat_size_list,d_out,bounding_op=lambda x: x ** 2, transformation=torch.tanh,dropout=0.0):
        super(mixed_layer_all, self).__init__()
        self.pos_weights = torch.nn.Parameter(torch.randn(*(d_in_bounded, d_out)), requires_grad=True)
        self.f = transformation
        self.bounding_op = bounding_op
        self.bias = torch.nn.Parameter(torch.randn(d_out), requires_grad=True)
        self.x_node = nn_node(d_in=d_in,d_out=d_out,cat_size_list=cat_size_list,dropout=dropout,transformation=lambda x:x)

    def forward(self,X,x_cat,x_bounded):
        return  self.f(x_bounded @ self.bounding_op(self.pos_weights) + self.bias + self.x_node(X,x_cat))

class mixed_layer_2(torch.nn.Module): #Add dropout layers
    def __init__(self, d_in, d_in_bounded, d_out, bounding_op=lambda x: x ** 2, transformation=torch.tanh):
        super(mixed_layer_2, self).__init__()
        self.pos_weights = torch.nn.Parameter(torch.randn(*(d_in_bounded, d_out//2)), requires_grad=True)
        self.f = transformation
        self.bounding_op = bounding_op
        self.bias = torch.nn.Parameter(torch.randn(d_out//2), requires_grad=True)
        self.w = torch.nn.Linear(d_in,d_out//2)

    def forward(self,X,x_bounded):
        bounded_part = x_bounded @ self.bounding_op(self.pos_weights) + self.bias
        regular_part = self.w(X)
        return self.f( torch.cat([bounded_part,regular_part],dim=1))



class survival_net_nocov(torch.nn.Module):
    def __init__(self,
                 d_in_x,
                 cat_size_list,
                 d_in_y,
                 d_out,
                 layers_x,
                 layers_t,
                 layers,
                 dropout=0.9,
                 bounding_op=lambda x: x**2,
                 transformation=torch.tanh,
                 direct_dif = True,
                 objective = 'hazard',
                 eps=1e-6
                 ):
        super(survival_net_nocov, self).__init__()
        self.init_middle_net(dx_in=d_in_x, d_in_y=d_in_y, d_out=d_out, layers=layers,
                             transformation=transformation, bounding_op=bounding_op,cat_size_list=cat_size_list)
        self.eps = eps
        self.direct = direct_dif
        self.objective  = objective

        if self.objective in ['hazard','hazard_mean']:
            self.f = self.forward_hazard
            self.f_cum = self.forward_cum_hazard
        elif self.objective in ['S','S_mean']:
            self.f=self.forward_f
            self.f_cum=self.forward_S


    def init_middle_net(self, dx_in, d_in_y, d_out,cat_size_list, layers, transformation, bounding_op):
        module_list = [mixed_layer_all( dx_in, d_in_y,cat_size_list,layers[0],bounding_op=bounding_op, transformation=transformation)]
        for l_i in range(1,len(layers)):
            module_list.append(bounded_nn_layer(d_in=layers[l_i - 1], d_out=layers[l_i], bounding_op=bounding_op,
                                                transformation=transformation))
        module_list.append(
            bounded_nn_layer_last(d_in=layers[-1], d_out=d_out, bounding_op=bounding_op, transformation=lambda x: x))
        self.middle_net = multi_input_Sequential_res_net(*module_list)

    def forward(self,x_cov,y,x_cat=[]):
        return self.f(x_cov,y,x_cat)

    def forward_cum(self,x_cov,y,mask,x_cat=[]):
        return self.f_cum(x_cov, y,mask,x_cat)

    def forward_S(self,x_cov,y,mask,x_cat=[]):
        x_cov = x_cov[~mask,:]
        y = y[~mask,:]
        if not isinstance(x_cat,list):
            x_cat=x_cat[~mask,:]
        #Fix categorical business
        h = self.middle_net((x_cov,x_cat,y))
        return -log1plusexp(h)

    def forward_f(self,x_cov,y,x_cat=[]):
        h = self.middle_net((x_cov,x_cat, y))
        h_forward = self.middle_net((x_cov,x_cat, y+self.eps))
        F = h.sigmoid()
        if self.direct:
            F_forward = h_forward.sigmoid()
            f = ((F_forward - F) / self.eps)
        else:
            dh = (h_forward - h) /self.eps
            f =dh*F*(1-F) #(F)*(1-F), F = h.sigmoid() log(sig(h)) + log(1-sig(h)) = h-2*log1plusexp(h)
        return f

    def forward_cum_hazard(self, x_cov, y, mask,x_cat=[]):
        h = self.middle_net((x_cov,x_cat, y))
        return log1plusexp(h)

    def forward_hazard(self, x_cov, y,x_cat=[]):
        h = self.middle_net((x_cov,x_cat,y))
        h_forward = self.middle_net((x_cov,x_cat,y+self.eps))
        if self.direct:
            hazard = (log1plusexp(h_forward) - log1plusexp(h)) / self.eps
        else:
            hazard = torch.sigmoid(h) * ((h_forward - h) / self.eps)
        return hazard

    def forward_S_eval(self,x_cov,y,x_cat=[]):
        if self.objective in ['hazard','hazard_mean']:
            S = torch.exp(-self.forward_cum_hazard(x_cov, y, [],x_cat))
            return S
        elif self.objective in ['S','S_mean']:
            h = self.middle_net((x_cov,x_cat, y))
            return 1-h.sigmoid_()



class survival_net_basic(torch.nn.Module):
    def __init__(self,
                 d_in_x,
                 cat_size_list,
                 d_in_y,
                 d_out,
                 layers_x,
                 layers_t,
                 layers,
                 dropout=0.9,
                 bounding_op=lambda x: x**2,
                 transformation=torch.tanh,
                 direct_dif = True,
                 objective = 'hazard',
                 eps=1e-6
                 ):
        super(survival_net_basic, self).__init__()
        self.init_covariate_net(d_in_x,layers_x,cat_size_list,transformation,dropout)
        self.init_middle_net(dx_in=layers_x[-1], d_in_y=d_in_y, d_out=d_out, layers=layers,
                             transformation=transformation, bounding_op=bounding_op)
        self.eps = eps
        self.direct = direct_dif
        self.objective  = objective

        if self.objective in ['hazard','hazard_mean']:
            self.f = self.forward_hazard
            self.f_cum = self.forward_cum_hazard
        elif self.objective in ['S','S_mean']:
            self.f=self.forward_f
            self.f_cum=self.forward_S

    def init_covariate_net(self,d_in_x,layers_x,cat_size_list,transformation,dropout):
        module_list = [nn_node(d_in=d_in_x,d_out=layers_x[0],cat_size_list=cat_size_list,transformation=transformation,dropout=dropout)]
        for l_i in range(1,len(layers_x)):
            module_list.append(nn_node(d_in=layers_x[l_i-1],d_out=layers_x[l_i],cat_size_list=[],transformation=transformation,dropout=dropout))
        self.covariate_net = multi_input_Sequential_res_net(*module_list)

    def init_middle_net(self, dx_in, d_in_y, d_out, layers, transformation, bounding_op):
        # self.mixed_layer = mixed_layer(d_in=dx_in, d_in_bounded=d_in_y, d_out=layers[0], transformation=transformation, bounding_op=bounding_op,dropout=dropout)
        module_list = [mixed_layer_2(d_in=dx_in, d_in_bounded=d_in_y, d_out=layers[0], bounding_op=bounding_op,
                                   transformation=transformation)]
        for l_i in range(1,len(layers)):
            module_list.append(bounded_nn_layer(d_in=layers[l_i - 1], d_out=layers[l_i], bounding_op=bounding_op,
                                                transformation=transformation))
        module_list.append(
            bounded_nn_layer_last(d_in=layers[-1], d_out=d_out, bounding_op=bounding_op, transformation=lambda x: x))
        self.middle_net = multi_input_Sequential_res_net(*module_list)

    def forward(self,x_cov,y,x_cat=[]):
        return self.f(x_cov,y,x_cat)

    def forward_cum(self,x_cov,y,mask,x_cat=[]):
        return self.f_cum(x_cov, y,mask,x_cat)

    def forward_S(self,x_cov,y,mask,x_cat=[]):
        x_cov = x_cov[~mask,:]
        y = y[~mask,:]
        if not isinstance(x_cat,list):
            x_cat=x_cat[~mask,:]
        #Fix categorical business
        x_cov = self.covariate_net((x_cov,x_cat))
        h = self.middle_net((x_cov,y))
        return -log1plusexp(h)

    def forward_f(self,x_cov,y,x_cat=[]): #Figure out how to zero out grad
        y = torch.autograd.Variable(y,requires_grad=True)
        x_cov = self.covariate_net((x_cov,x_cat))
        h = self.middle_net((x_cov, y))
        F = h.sigmoid()
        if self.direct=='full':
            h_forward = self.middle_net((x_cov, y + self.eps))
            F_forward = h_forward.sigmoid()
            f = ((F_forward - F) / self.eps)
        elif self.direct=='semi':
            h_forward = self.middle_net((x_cov, y + self.eps))
            dh = (h_forward - h) /self.eps
            f =dh*F*(1-F)
        else:
            f, = torch.autograd.grad(
                outputs=[F],
                inputs=[y],
                grad_outputs=torch.ones_like(F),
                retain_graph=True,
                create_graph=True,
                only_inputs=True,
                allow_unused=True
            )

        return f

    def forward_cum_hazard(self, x_cov, y, mask,x_cat=[]):
        x_cov = self.covariate_net((x_cov,x_cat))
        h = self.middle_net((x_cov, y))
        return log1plusexp(h)

    def forward_hazard(self, x_cov, y,x_cat=[]):
        y = torch.autograd.Variable(y,requires_grad=True)
        x_cov = self.covariate_net((x_cov,x_cat))
        h = self.middle_net((x_cov,y))
        if self.direct=='full':
            h_forward = self.middle_net((x_cov, y + self.eps))
            hazard = (log1plusexp(h_forward) - log1plusexp(h)) / self.eps
        elif self.direct == 'semi':
            h_forward = self.middle_net((x_cov, y + self.eps))
            hazard = torch.sigmoid(h) * ((h_forward - h) / self.eps)
        else:
            H=log1plusexp(h)
            hazard, = torch.autograd.grad(
                outputs=[H],
                inputs=[y],
                grad_outputs=torch.ones_like(H),
                retain_graph=True,
                create_graph=True,
                only_inputs=True,
                allow_unused=True
            )
        return hazard

    def forward_S_eval(self,x_cov,y,x_cat=[]):
        if self.objective in ['hazard','hazard_mean']:
            S = torch.exp(-self.forward_cum_hazard(x_cov, y, [],x_cat))
            return S
        elif self.objective in ['S','S_mean']:
            x_cov = self.covariate_net((x_cov,x_cat))
            h = self.middle_net((x_cov, y))
            return 1-h.sigmoid_()

class survival_net(torch.nn.Module):
    def __init__(self,
                 d_in_x,
                 cat_size_list,
                 d_in_y,
                 d_out,
                 layers_x,
                 layers_t,
                 layers,
                 dropout=0.9,
                 bounding_op=lambda x: x**2,
                 transformation=torch.tanh,
                 direct_dif = True,
                 objective = 'hazard',
                 eps=1e-6
                 ):
        super(survival_net, self).__init__()
        self.init_covariate_net(d_in_x,layers_x,cat_size_list,transformation,dropout)
        self.init_middle_net(dx_in=layers_x[-1], d_in_y=d_in_y, d_out=d_out, layers=layers,
                             transformation=transformation, bounding_op=bounding_op)
        self.net_t = self.init_bounded_net(d_in_y,d_out,layers_t,transformation,bounding_op)
        self.eps = eps
        self.direct = direct_dif
        self.objective  = objective

        if self.objective in ['hazard','hazard_mean']:
            self.f = self.forward_hazard
            self.f_cum = self.forward_cum_hazard
        elif self.objective in ['S','S_mean']:
            self.f=self.forward_f
            self.f_cum=self.forward_S

    def init_bounded_net(self, dx_in, d_out, layers, transformation, bounding_op):
        # self.mixed_layer = mixed_layer(d_in=dx_in, d_in_bounded=d_in_y, d_out=layers[0], transformation=transformation, bounding_op=bounding_op,dropout=dropout)
        module_list = [bounded_nn_layer(d_in=dx_in, d_out=layers[0], bounding_op=bounding_op,
                                        transformation=transformation)]
        for l_i in range(1, len(layers)):
            module_list.append(bounded_nn_layer(d_in=layers[l_i - 1], d_out=layers[l_i], bounding_op=bounding_op,
                                                transformation=transformation))
        module_list.append(
            bounded_nn_layer_last(d_in=layers[-1], d_out=d_out, bounding_op=bounding_op, transformation=lambda x: x))
        return multi_input_Sequential_res_net(*module_list)

    def init_covariate_net(self,d_in_x,layers_x,cat_size_list,transformation,dropout):
        module_list = [nn_node(d_in=d_in_x,d_out=layers_x[0],cat_size_list=cat_size_list,transformation=transformation,dropout=dropout)]
        for l_i in range(1,len(layers_x)):
            module_list.append(nn_node(d_in=layers_x[l_i-1],d_out=layers_x[l_i],cat_size_list=[],transformation=transformation,dropout=dropout))
        self.covariate_net = multi_input_Sequential_res_net(*module_list)

    def init_middle_net(self, dx_in, d_in_y, d_out, layers, transformation, bounding_op):
        # self.mixed_layer = mixed_layer(d_in=dx_in, d_in_bounded=d_in_y, d_out=layers[0], transformation=transformation, bounding_op=bounding_op,dropout=dropout)
        module_list = [mixed_layer_2(d_in=dx_in, d_in_bounded=d_in_y, d_out=layers[0], bounding_op=bounding_op,
                                   transformation=transformation)]
        for l_i in range(1,len(layers)):
            module_list.append(bounded_nn_layer(d_in=layers[l_i - 1], d_out=layers[l_i], bounding_op=bounding_op,
                                                transformation=transformation))
        module_list.append(
            bounded_nn_layer_last(d_in=layers[-1], d_out=d_out, bounding_op=bounding_op, transformation=lambda x: x))
        self.middle_net = multi_input_Sequential_res_net(*module_list)



    def forward(self,x_cov,y,x_cat=[]):
        return self.f(x_cov,y,x_cat)

    def forward_cum(self,x_cov,y,mask,x_cat=[]):
        return self.f_cum(x_cov, y,mask,x_cat)

    def forward_S(self,x_cov,y,mask,x_cat=[]):
        x_cov = x_cov[~mask,:]
        y = y[~mask,:]
        if not isinstance(x_cat,list):
            x_cat=x_cat[~mask,:]
        #Fix categorical business
        x_cov = self.covariate_net((x_cov,x_cat))
        h = self.middle_net((x_cov,self.net_t(y)))
        return -log1plusexp(h)

    def forward_f(self,x_cov,y,x_cat=[]):
        y = torch.autograd.Variable(y,requires_grad=True)
        x_cov = self.covariate_net((x_cov,x_cat))
        nt = self.net_t(y)
        h = self.middle_net((x_cov, nt))
        F = h.sigmoid()

        if self.direct == 'full':
            nt_plus_h = self.net_t(y + self.eps)
            h_forward = self.middle_net((x_cov, nt_plus_h))
            F_forward = h_forward.sigmoid()
            f = ((F_forward - F) / self.eps)
        elif self.direct == 'semi':
            h_forward = self.middle_net((x_cov, y + self.eps))
            dh = (h_forward - h) / self.eps
            f = dh * F * (1 - F)
        else:
            f, = torch.autograd.grad(
                outputs=[F],
                inputs=[y],
                grad_outputs=torch.ones_like(F),
                retain_graph=True,
                create_graph=True,
                only_inputs=True,
                allow_unused=True
            )

        return f

    def forward_cum_hazard(self, x_cov, y, mask,x_cat=[]):
        x_cov = self.covariate_net((x_cov,x_cat))
        h = self.middle_net((x_cov, self.net_t(y)))
        return log1plusexp(h)

    def forward_hazard(self, x_cov, y,x_cat=[]):
        y = torch.autograd.Variable(y,requires_grad=True)
        x_cov = self.covariate_net((x_cov,x_cat))
        h = self.middle_net((x_cov, self.net_t(y)))
        if self.direct=='full':
            h_forward = self.middle_net((x_cov, self.net_t(y + self.eps)))
            hazard = (log1plusexp(h_forward) - log1plusexp(h)) / self.eps
        elif self.direct == 'semi':
            h_forward = self.middle_net((x_cov, self.net_t(y + self.eps)))
            hazard = torch.sigmoid(h) * ((h_forward - h) / self.eps)
        else:
            H=log1plusexp(h)
            hazard, = torch.autograd.grad(
                outputs=[H],
                inputs=[y],
                grad_outputs=torch.ones_like(H),
                retain_graph=True,
                create_graph=True,
                only_inputs=True,
                allow_unused=True
            )
        return hazard

    def forward_S_eval(self,x_cov,y,x_cat=[]):
        if self.objective in ['hazard','hazard_mean']:
            S = torch.exp(-self.forward_cum_hazard(x_cov, y, [],x_cat))
            return S
        elif self.objective in ['S','S_mean']:
            x_cov = self.covariate_net((x_cov,x_cat))
            h = self.middle_net((x_cov, self.net_t(y)))
            return 1-h.sigmoid_()

class survival_net_variant(survival_net):
    def __init__(self,
                 d_in_x,
                 cat_size_list,
                 d_in_y,
                 d_out,
                 layers_x,
                 layers_t,
                 layers,
                 dropout=0.9,
                 bounding_op=lambda x: x ** 2,
                 transformation=torch.tanh,
                 direct_dif=True,
                 objective='hazard',
                 eps=1e-6
                 ):
        super(survival_net_variant, self).__init__(d_in_x,
                 cat_size_list,
                 d_in_y,
                 d_out,
                 layers_x,
                 layers_t,
                 layers,
                 dropout,
                 bounding_op,
                 transformation,
                 direct_dif,
                 objective)
        self.init_covariate_net(d_in_x,layers_x,cat_size_list,transformation,dropout)
        self.init_final_output(dx_in=layers_x[-1], d_in_y=d_in_y, d_out=d_out, bounding_op=bounding_op)
        self.net_t = self.init_bounded_net(d_in_y,d_out,layers_t,transformation,bounding_op)
        self.eps = eps
        self.direct = direct_dif
        self.objective  = objective

    def init_final_output(self, dx_in, d_in_y, d_out, bounding_op):
        module_list = [mixed_layer(d_in=dx_in, d_in_bounded=d_in_y, d_out=d_out, bounding_op=bounding_op,
                                   transformation=lambda x: x)]
        self.middle_net = multi_input_Sequential_res_net(*module_list)

class ocean_net(torch.nn.Module):
    def __init__(self,
                 d_in_x,
                 cat_size_list,
                 d_in_y,
                 d_out,
                 layers_x,
                 layers_t,
                 layers,
                 dropout=0.9,
                 bounding_op=lambda x: x ** 2,
                 transformation=torch.tanh,
                 direct_dif=True,
                 objective='S_mean',
                 eps=1e-5
                 ):
        super(ocean_net, self).__init__()

        self.bounding_op = bounding_op
        self.covariate_net = self.init_covariate_net(d_in_x, layers_x, cat_size_list, transformation, dropout)
        self.middle_net = self.init_middle_net(dx_in=layers_x[-1], d_in_y=d_in_y, d_out=d_out, layers=layers,
                             transformation=transformation, bounding_op=bounding_op)
        self.prod_net_t = self.init_bounded_net(d_in_y,d_out,layers_t,transformation,bounding_op)
        self.prod_net_x = self.init_covariate_net_2(d_in_x, layers_x,d_out, cat_size_list, transformation, dropout)

        self.net_t = self.init_bounded_net(d_in_y,d_out,layers_t,transformation,bounding_op)
        self.net_x = self.init_covariate_net_2(d_in_x, layers_x,d_out, cat_size_list, transformation, dropout)

        self.net_t_pre = self.init_bounded_net(d_in_y,d_out,layers_t,transformation,bounding_op)

        self.eps = eps
        self.direct = direct_dif
        self.objective = objective
        if self.objective in ['hazard', 'hazard_mean']:
            self.f = self.forward_hazard
            self.f_cum = self.forward_cum_hazard
        elif self.objective in ['S', 'S_mean']:
            self.f = self.forward_f
            self.f_cum = self.forward_S

    def init_covariate_net(self, d_in_x, layers_x, cat_size_list, transformation, dropout):
        module_list = [
            nn_node(d_in=d_in_x, d_out=layers_x[0], cat_size_list=cat_size_list, transformation=transformation,
                    dropout=dropout)]
        for l_i in range(1, len(layers_x)):
            module_list.append(
                nn_node(d_in=layers_x[l_i - 1], d_out=layers_x[l_i], cat_size_list=[], transformation=transformation,
                        dropout=dropout))
        return multi_input_Sequential_res_net(*module_list)

    def init_covariate_net_2(self, d_in_x, layers_x,d_out, cat_size_list, transformation, dropout):
        module_list = [
            nn_node(d_in=d_in_x, d_out=layers_x[0], cat_size_list=cat_size_list, transformation=transformation,
                    dropout=dropout)]
        for l_i in range(1, len(layers_x)):
            module_list.append(
                nn_node(d_in=layers_x[l_i - 1], d_out=layers_x[l_i], cat_size_list=[], transformation=transformation,
                        dropout=dropout))
        module_list.append(
            nn_node(d_in=layers_x[ -1], d_out=d_out, cat_size_list=[], transformation=transformation,
                    dropout=dropout))
        return multi_input_Sequential_res_net(*module_list)

    def init_middle_net(self, dx_in, d_in_y, d_out, layers, transformation, bounding_op):
        # self.mixed_layer = mixed_layer(d_in=dx_in, d_in_bounded=d_in_y, d_out=layers[0], transformation=transformation, bounding_op=bounding_op,dropout=dropout)
        module_list = [mixed_layer(d_in=dx_in, d_in_bounded=d_in_y, d_out=layers[0], bounding_op=bounding_op,
                                   transformation=transformation)]
        for l_i in range(1, len(layers)):
            module_list.append(bounded_nn_layer(d_in=layers[l_i - 1], d_out=layers[l_i], bounding_op=bounding_op,
                                                transformation=transformation))
        module_list.append(
            bounded_nn_layer_last(d_in=layers[-1], d_out=d_out, bounding_op=bounding_op, transformation=lambda x: x))
        return multi_input_Sequential_res_net(*module_list)

    def init_bounded_net(self, dx_in, d_out, layers, transformation, bounding_op):
        # self.mixed_layer = mixed_layer(d_in=dx_in, d_in_bounded=d_in_y, d_out=layers[0], transformation=transformation, bounding_op=bounding_op,dropout=dropout)
        module_list = [bounded_nn_layer(d_in=dx_in, d_out=layers[0], bounding_op=bounding_op,
                                   transformation=transformation)]
        for l_i in range(1, len(layers)):
            module_list.append(bounded_nn_layer(d_in=layers[l_i - 1], d_out=layers[l_i], bounding_op=bounding_op,
                                                transformation=transformation))
        module_list.append(
            bounded_nn_layer_last(d_in=layers[-1], d_out=d_out, bounding_op=bounding_op, transformation=lambda x: x))
        return multi_input_Sequential_res_net(*module_list)

    def forward(self, x_cov, y, x_cat=[]):
        return self.f(x_cov, y, x_cat)

    def forward_cum(self, x_cov, y, mask, x_cat=[]):
        return self.f_cum(x_cov, y, mask, x_cat)

    def forward_S(self, x_cov_in, y, mask, x_cat=[]):
        x_cov_in = x_cov_in[~mask, :]
        y = y[~mask, :]
        if not isinstance(x_cat, list):
            x_cat = x_cat[~mask, :]
        # Fix categorical business
        x_cov = self.covariate_net((x_cov_in, x_cat))
        h_xt = self.middle_net((x_cov, self.net_t_pre(y)))
        h_xh_t = self.prod_net_t(y)* self.bounding_op(self.prod_net_x((x_cov_in, x_cat)))
        h_t = self.net_t(y)
        h_x = self.net_x((x_cov_in, x_cat))
        h = h_xh_t + h_t + h_x +h_xt
        return -log1plusexp(h)

    def forward_f(self, x_cov_in, y, x_cat=[]):
        x_cov = self.covariate_net((x_cov_in, x_cat))
        h_xt = self.middle_net((x_cov, self.net_t_pre(y)))
        h_xt_forward = self.middle_net((x_cov, self.net_t_pre(y + self.eps)))
        h_t = self.net_t((y))
        h_t_forward = self.net_t((y+ self.eps))
        prod_x = self.bounding_op(self.prod_net_x((x_cov_in, x_cat)))
        h_xh_t = self.prod_net_t((y))
        h_xh_t_forward = self.prod_net_t((y+self.eps))
        h_x = self.net_x((x_cov_in, x_cat))
        h = h_xt + h_xh_t*prod_x + h_t + h_x
        F = h.sigmoid()

        if self.direct:
            F_forward = (h_xt_forward + h_xh_t_forward*prod_x + h_t_forward + h_x).sigmoid()
            f = ((F_forward - F) / self.eps)
        else:
            diff = h_xt_forward+h_t_forward-(h_xt + h_t) + prod_x*(h_xh_t_forward-h_xh_t)
            f = (diff / self.eps) * F * (
                        1 - F)  # (F)*(1-F), F = h.sigmoid() log(sig(h)) + log(1-sig(h)) = h-2*log1plusexp(h)
        return f

    def forward_cum_hazard(self, x_cov_in, y, mask, x_cat=[]):
        x_cov = self.covariate_net((x_cov_in, x_cat))
        h_xt = self.middle_net((x_cov, self.net_t_pre(y)))
        h_xh_t = self.prod_net_t(y)*self.bounding_op(self.prod_net_x((x_cov_in, x_cat)))
        h_t = self.net_t(y)
        h_x = self.net_x((x_cov_in, x_cat))
        h = h_xt + h_xh_t + h_t + h_x

        return log1plusexp(h)

    def forward_hazard(self, x_cov_in, y, x_cat=[]):
        x_cov = self.covariate_net((x_cov_in, x_cat))
        h_xt = self.middle_net((x_cov,  self.net_t_pre(y)))
        h_xt_forward = self.middle_net((x_cov, self.net_t_pre(y + self.eps)))
        h_t = self.net_t((y))
        h_t_forward = self.net_t((y+ self.eps))
        prod_x =self.bounding_op(self.prod_net_x((x_cov_in, x_cat)))
        h_xh_t = self.prod_net_t((y))
        h_xh_t_forward = self.prod_net_t((y+self.eps))
        h_x = self.net_x((x_cov_in, x_cat))
        h = h_xt + h_xh_t*prod_x + h_t + h_x

        if self.direct:
            h_forward = h_xt_forward + h_xh_t_forward*prod_x + h_t_forward + h_x
            hazard = (log1plusexp(h_forward) - log1plusexp(h)) / self.eps
        else:
            diff = h_xt_forward+h_t_forward-(h_xt + h_t) + prod_x*(h_xh_t_forward-h_xh_t)
            hazard = torch.sigmoid(h) * (diff / self.eps)
        return hazard

    def forward_S_eval(self, x_cov_in, y, x_cat=[]):

        if self.objective in ['hazard', 'hazard_mean']:
            S = torch.exp(-self.forward_cum_hazard(x_cov_in, y, [], x_cat))
            return S

        elif self.objective in ['S', 'S_mean']:
            x_cov = self.covariate_net((x_cov_in, x_cat))
            h_xt = self.middle_net((x_cov,  self.net_t_pre(y)))
            h_xh_t = self.prod_net_t((y)) * self.bounding_op(self.prod_net_x((x_cov_in, x_cat)))
            h_t = self.net_t((y))
            h_x = self.net_x((x_cov_in, x_cat))
            h = h_xt + h_xh_t + h_t + h_x
            return 1 - h.sigmoid_()


class cox_net(torch.nn.Module):
    def __init__(self,
                 d_in_x,
                 cat_size_list,
                 d_in_y,
                 d_out,
                 layers_x,
                 layers,
                 dropout=0.9,
                 bounding_op=lambda x: x ** 2,
                 transformation=torch.tanh,
                 direct_dif=True,
                 objective='S_mean',
                 eps=1e-6
                 ):
        super(cox_net, self).__init__()

        self.bounding_op = bounding_op

        self.net_t = self.init_bounded_net(d_in_y,d_out,layers,transformation,bounding_op)
        self.net_x = self.init_covariate_net_2(d_in_x, layers_x,d_out, cat_size_list, transformation, dropout)


        self.eps = eps
        self.direct = direct_dif
        self.objective = objective
        if self.objective in ['hazard', 'hazard_mean']:
            self.f = self.forward_hazard
            self.f_cum = self.forward_cum_hazard
        elif self.objective in ['S', 'S_mean']:
            self.f = self.forward_f
            self.f_cum = self.forward_S

    def init_covariate_net_2(self, d_in_x, layers_x,d_out, cat_size_list, transformation, dropout):
        module_list = [
            nn_node(d_in=d_in_x, d_out=layers_x[0], cat_size_list=cat_size_list, transformation=transformation,
                    dropout=dropout)]
        for l_i in range(1, len(layers_x)):
            module_list.append(
                nn_node(d_in=layers_x[l_i - 1], d_out=layers_x[l_i], cat_size_list=[], transformation=transformation,
                        dropout=dropout))
        module_list.append(
            nn_node(d_in=layers_x[ -1], d_out=d_out, cat_size_list=[], transformation=transformation,
                    dropout=dropout))
        return multi_input_Sequential_res_net(*module_list)

    def init_bounded_net(self, dx_in, d_out, layers, transformation, bounding_op):
        # self.mixed_layer = mixed_layer(d_in=dx_in, d_in_bounded=d_in_y, d_out=layers[0], transformation=transformation, bounding_op=bounding_op,dropout=dropout)
        module_list = [bounded_nn_layer(d_in=dx_in, d_out=layers[0], bounding_op=bounding_op,
                                   transformation=transformation)]
        for l_i in range(1, len(layers)):
            module_list.append(bounded_nn_layer(d_in=layers[l_i - 1], d_out=layers[l_i], bounding_op=bounding_op,
                                                transformation=transformation))
        module_list.append(
            bounded_nn_layer(d_in=layers[-1], d_out=d_out, bounding_op=bounding_op, transformation=lambda x: x))
        return multi_input_Sequential_res_net(*module_list)

    def forward(self, x_cov, y, x_cat=[]):
        return self.f(x_cov, y, x_cat)

    def forward_cum(self, x_cov, y, mask, x_cat=[]):
        return self.f_cum(x_cov, y, mask, x_cat)

    def forward_S(self, x_cov_in, y, mask, x_cat=[]):
        x_cov_in = x_cov_in[~mask, :]
        y = y[~mask, :]
        if not isinstance(x_cat, list):
            x_cat = x_cat[~mask, :]
        # Fix categorical business
        h_t = self.net_t((y))
        h_x = self.net_x((x_cov_in, x_cat))
        h = h_t + h_x
        return -log1plusexp(h)

    def forward_f(self, x_cov_in, y, x_cat=[]):
        h_t = self.net_t((y))
        h_t_forward = self.net_t((y+ self.eps))
        h_x = self.net_x((x_cov_in, x_cat))
        h = h_t + h_x
        F = h.sigmoid()

        if self.direct:
            F_forward = ( h_t_forward + h_x).sigmoid()
            f = ((F_forward - F) / self.eps)
        else:
            diff = (h_t_forward - h_t)
            f = (diff / self.eps) * F * (
                        1 - F)  # (F)*(1-F), F = h.sigmoid() log(sig(h)) + log(1-sig(h)) = h-2*log1plusexp(h)
        return f

    def forward_cum_hazard(self, x_cov_in, y, mask, x_cat=[]):
        h_t = self.net_t((y))
        h_x = self.net_x((x_cov_in, x_cat))
        h =  h_t + h_x

        return log1plusexp(h)

    def forward_hazard(self, x_cov_in, y, x_cat=[]):
        h_t = self.net_t((y))
        h_t_forward = self.net_t((y+ self.eps))
        h_x = self.net_x((x_cov_in, x_cat))
        h =h_x + h_t
        if self.direct:
            h_forward = h_t_forward+h_x
            hazard = (log1plusexp(h_forward) - log1plusexp(h)) / self.eps
        else:
            diff = (h_t_forward-h_t)
            hazard = torch.sigmoid(h) * (diff / self.eps)
        return hazard

    def forward_S_eval(self, x_cov_in, y, x_cat=[]):

        if self.objective in ['hazard', 'hazard_mean']:
            S = torch.exp(-self.forward_cum_hazard(x_cov_in, y, [], x_cat))
            return S

        elif self.objective in ['S', 'S_mean']:
            h_t = self.net_t((y))
            h_x = self.net_x((x_cov_in, x_cat))
            h = h_t+h_x
            return 1 - h.sigmoid_()

def get_objective(objective):
    if objective == 'hazard':
        return log_objective_hazard
    if objective == 'hazard_mean':
        return log_objective_hazard_mean
    elif objective == 'S':
        return log_objective
    elif objective=='S_mean':
        return log_objective_mean

def log_objective(S,f):
    return -(f+1e-6).log().sum()-S.sum()

def log_objective_mean(S,f):
    n = S.shape[0]+f.shape[0]
    return -((f+1e-6).log().sum()+S.sum())/n

def log_objective_hazard(cum_hazard,hazard): #here cum_hazard should be a vector of
    # length n, and hazard only needs to be computed for all individuals with
    # delta = 1 I'm not sure how to implement that best?
    return -(  (hazard+1e-6).log().sum()-cum_hazard.sum() )

def log_objective_hazard_mean(cum_hazard,hazard):
    n = cum_hazard.shape[0]
    return -(  (hazard+1e-6).log().sum()-cum_hazard.sum() )/n













