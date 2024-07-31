## Create parameters for Support and Metabric

```shell
python generate_job_parameters.py
```

## Run fit and evaluation

```shell
python serious_run.py --job_path {support_params, databric_params} --random_state [0, 4]
```