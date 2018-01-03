import os
import sys
import glob

import pandas as pd
import numpy as np

from numerox.metrics import metrics_per_era
from numerox.metrics import metrics_per_model
from numerox.metrics import pearsonr
from numerox.metrics import ks_2samp

if sys.version_info[0] == 2:
    base_string = basestring
else:
    base_string = str

HDF_PREDICTION_KEY = 'numerox_prediction'


class Prediction(object):

    def __init__(self, df=None):
        self.df = df

    @property
    def names(self):
        if self.df is None:
            return []
        return self.df.columns.tolist()

    def iter(self):
        "Yield a prediction object with only one model at a time"
        for name in self.names:
            yield self[name]

    def append_arrays(self, ids, yhat, name):
        "Append numpy arrays ids and yhat with name prediction_name"
        df = pd.DataFrame(data={name: yhat}, index=ids)
        prediction = Prediction(df)
        self.append_prediction(prediction)

    def append_prediction(self, prediction):
        if prediction.df.shape[1] != 1:
            raise NotImplementedError("TODO: handle more than one model")
        name = prediction.names[0]
        if self.df is None:
            # empty prediction
            self.df = prediction.df
        elif name not in self:
            # inserting predictions from a model not already in report
            self.df = pd.merge(self.df, prediction.df, how='outer',
                               left_index=True, right_index=True)
        else:
            # add more yhats from a model whose name already exists
            y = self.df[name]
            y = y.dropna()
            s = prediction.df.iloc[:, 0]
            s = s.dropna()
            s = pd.concat([s, y], join='outer', ignore_index=False,
                          verify_integrity=True)
            df = s.to_frame(name)
            self.df = pd.merge(self.df, df, how='outer', on=name,
                               left_index=True, right_index=True)

    def summary(self, data, name):
        df = self.summary_df(data, name)
        df = df.round(decimals={'logloss': 6, 'auc': 4, 'acc': 4, 'ystd': 4})
        with pd.option_context('display.colheader_justify', 'left'):
            print(df.to_string(index=True))

    def summary_df(self, data, name):

        # metrics
        pred = self[name]
        metrics, regions = metrics_per_era(data, pred, region_as_str=True)
        metrics = metrics.drop(['era', 'model'], axis=1)

        # additional metrics
        region_str = ', '.join(regions)
        nera = metrics.shape[0]
        logloss = metrics['logloss']
        consis = (logloss < np.log(2)).mean()
        sharpe = (np.log(2) - logloss).mean() / logloss.std()

        # summary of metrics
        m1 = metrics.mean(axis=0).tolist() + ['region', region_str]
        m2 = metrics.std(axis=0).tolist() + ['eras', nera]
        m3 = metrics.min(axis=0).tolist() + ['sharpe', sharpe]
        m4 = metrics.max(axis=0).tolist() + ['consis', consis]
        data = [m1, m2, m3, m4]

        # make dataframe
        columns = metrics.columns.tolist() + ['stats', '']
        df = pd.DataFrame(data=data,
                          index=['mean', 'std', 'min', 'max'],
                          columns=columns)

        return df

    def performance_per_era(self, data, name):
        print(name)
        df = self.df[name].to_frame(name)
        df = metrics_per_era(data, Prediction(df))[name]
        df = df.round(decimals={'logloss': 6, 'auc': 4, 'acc': 4, 'ystd': 4})
        with pd.option_context('display.colheader_justify', 'left'):
            print(df.to_string())

    def performance(self, data, sort_by='logloss'):
        df, info = self.performance_df(data)
        if sort_by == 'logloss':
            df = df.sort_values(by='logloss', ascending=True)
        elif sort_by == 'auc':
            df = df.sort_values(by='auc', ascending=False)
        elif sort_by == 'acc':
            df = df.sort_values(by='acc', ascending=False)
        elif sort_by == 'ystd':
            df = df.sort_values(by='ystd', ascending=False)
        elif sort_by == 'sharpe':
            df = df.sort_values(by='sharpe', ascending=False)
        elif sort_by == 'consis':
            df = df.sort_values(by=['consis', 'logloss'],
                                ascending=[False, True])
        else:
            raise ValueError("`sort_by` name not recognized")
        df = df.round(decimals={'logloss': 6, 'auc': 4, 'acc': 4, 'ystd': 4,
                                'sharpe': 4, 'consis': 4})
        info_str = ', '.join(info['region']) + '; '
        info_str += '{} eras'.format(len(info['era']))
        print(info_str)
        with pd.option_context('display.colheader_justify', 'left'):
            print(df.to_string(index=True))

    def performance_df(self, data, era_as_str=True, region_as_str=True):
        cols = ['logloss', 'auc', 'acc', 'ystd', 'sharpe', 'consis']
        metrics, info = metrics_per_model(data,
                                          self,
                                          columns=cols,
                                          era_as_str=era_as_str,
                                          region_as_str=region_as_str)
        return metrics, info

    def dominance(self, data, sort_by='logloss'):
        "Mean (across eras) of fraction of models bested per era"
        df = self.dominance_df(data)
        df = df.sort_values([sort_by], ascending=[False])
        df = df.round(decimals=4)
        with pd.option_context('display.colheader_justify', 'left'):
            print(df.to_string(index=True))

    def dominance_df(self, data):
        "Mean (across eras) of fraction of models bested per era"
        columns = ['logloss', 'auc', 'acc']
        mpe, regions = metrics_per_era(data, self, columns=columns)
        dfs = []
        for i, col in enumerate(columns):
            pivot = mpe.pivot(index='era', columns='model', values=col)
            models = pivot.columns.tolist()
            a = pivot.values
            n = a.shape[1] - 1.0
            if n == 0:
                raise ValueError("Must have at least two models")
            m = []
            for j in range(pivot.shape[1]):
                if col == 'logloss':
                    z = (a[:, j].reshape(-1, 1) < a).sum(axis=1) / n
                else:
                    z = (a[:, j].reshape(-1, 1) > a).sum(axis=1) / n
                m.append(z.mean())
            df = pd.DataFrame(data=m, index=models, columns=[col])
            dfs.append(df)
        df = pd.concat(dfs, axis=1)
        return df

    def correlation(self, name=None):
        "Correlation of predictions; by default reports given for each model"
        if name is None:
            names = self.names
        else:
            names = [name]
        z = self.df.values
        znames = self.names
        idx = np.isfinite(z.sum(axis=1))
        z = z[idx]
        z = (z - z.mean(axis=0)) / z.std(axis=0)
        for name in names:
            print(name)
            idx = znames.index(name)
            corr = np.dot(z[:, idx], z) / z.shape[0]
            index = (-corr).argsort()
            for ix in index:
                zname = znames[ix]
                if name != zname:
                    print("   {:.4f} {}".format(corr[ix], zname))

    def originality(self, submitted_names):
        "Which models are original given the models already submitted?"

        # predictions of models already submitted
        yhats = self.df[submitted_names].values

        # models that have not been submitted; we will report on these
        names = self.names
        names = [m for m in names if m not in submitted_names]

        # originality
        df = pd.DataFrame(index=names, columns=['corr', 'ks', 'original'])
        for name in names:
            corr = True
            ks = True
            yhat = self.df[name].values
            for i in range(yhats.shape[1]):
                if corr and pearsonr(yhat, yhats[:, i]) > 0.95:
                    corr = False
                if ks and ks_2samp(yhat, yhats[:, i]) <= 0.03:
                    ks = False
            df.loc[name, 'corr'] = corr
            df.loc[name, 'ks'] = ks
            df.loc[name, 'original'] = corr and ks

        return df

    def __getitem__(self, name):
        "Prediction indexing is by model name(s)"
        if isinstance(name, base_string):
            p = Prediction(self.df[name].to_frame(name))
        else:
            p = Prediction(self.df[name])
        return p

    def __setitem__(self, name, prediction):
        "Add (or replace) a prediction"
        if prediction.df.shape[1] != 1:
            raise ValueError("Can only insert a single model at a time")
        prediction.df.columns = [name]
        self.append_prediction(prediction)

    def __contains__(self, name):
        "Is `name` already in prediction? True or False"
        return name in self.df

    @property
    def size(self):
        if self.df is None:
            return 0
        return self.df.size

    @property
    def shape(self):
        if self.df is None:
            return tuple()
        return self.df.shape

    def __len__(self):
        "Number of rows"
        if self.df is None:
            return 0
        return self.df.__len__()


def load_report(prediction_dir, extension='pred'):
    "Load Prediction objects (hdf) in `prediction_dir`"
    original_dir = os.getcwd()
    os.chdir(prediction_dir)
    predictions = {}
    try:
        for filename in glob.glob("*{}".format(extension)):
            prediction = load_prediction(filename)
            model = filename[:-len(extension) - 1]
            predictions[model] = prediction
    finally:
        os.chdir(original_dir)
    report = Prediction()
    report.append_prediction_dict(predictions)
    return report


class Prediction_OLD(object):

    def __init__(self, df=None):
        self.df = df

    @property
    def ids(self):
        "View of ids as a numpy str array"
        return self.df.index.values

    @property
    def yhat(self):
        "View of yhat as a 1d numpy float array"
        return self.df['yhat'].values

    def yhatnew(self, y_array):
        "Copy of prediction but with prediction.yhat=`y_array`"
        if y_array.shape[0] != len(self):
            msg = "`y_array` must have the same number of rows as prediction"
            raise ValueError(msg)
        if y_array.ndim != 1:
            raise ValueError("`y_array` must be 1 dimensional")
        df = pd.DataFrame(data=np.empty((y_array.shape[0],), dtype=np.float64),
                          index=self.df.index.copy(deep=True),
                          columns=['yhat'])
        df['yhat'] = y_array
        return Prediction(df)

    def append(self, ids, yhat):
        df = pd.DataFrame(data={'yhat': yhat}, index=ids)
        if self.df is None:
            df.index.rename('ids', inplace=True)
        else:
            try:
                df = pd.concat([self.df, df], verify_integrity=True)
            except ValueError:
                # pandas doesn't raise expected IndexError and for our large
                # number of y, the id overlaps that it prints can be very long
                raise IndexError("Overlap in ids found")
        self.df = df

    def to_csv(self, path_or_buf=None, decimals=6, verbose=False):
        "Save a csv file of predictions for later upload to Numerai"
        df = self.df.copy()
        df.index.rename('id', inplace=True)
        df.rename(columns={'yhat': 'probability'}, inplace=True)
        float_format = "%.{}f".format(decimals)
        df.to_csv(path_or_buf, float_format=float_format)
        if verbose:
            print("Save {}".format(path_or_buf))

    def save(self, path_or_buf, compress=True):
        "Save prediction as an hdf archive; raises if nothing to save"
        if self.df is None:
            raise ValueError("Prediction object is empty; nothing to save")
        if compress:
            self.df.to_hdf(path_or_buf, HDF_PREDICTION_KEY,
                           complib='zlib', complevel=4)
        else:
            self.df.to_hdf(path_or_buf, HDF_PREDICTION_KEY)

    def consistency(self, data):
        "Consistency over eras in `data`"
        logloss = self.metrics_per_era(data, metrics=['logloss'])
        c = (logloss.values < np.log(2)).mean()
        return c

    def metrics_per_era(self, data, metrics=['logloss'], era_as_str=True):
        "DataFrame containing given metrics versus era"
        metrics, regions = metrics_per_era(data, self, columns=metrics,
                                           era_as_str=era_as_str)
        metrics.index = metrics['era']
        metrics = metrics.drop(['era', 'model'], axis=1)
        return metrics

    def performance(self, data):
        df = self.performance_df(data)
        df = df.round(decimals={'logloss': 6, 'auc': 4, 'acc': 4, 'ystd': 4})
        with pd.option_context('display.colheader_justify', 'left'):
            print(df.to_string(index=True))

    def performance_df(self, data):

        # metrics
        metrics, regions = metrics_per_era(data, self, region_as_str=True)
        metrics = metrics.drop(['era', 'model'], axis=1)

        # additional metrics
        region_str = ', '.join(regions)
        nera = metrics.shape[0]
        logloss = metrics['logloss']
        consis = (logloss < np.log(2)).mean()
        sharpe = (np.log(2) - logloss).mean() / logloss.std()

        # summary of metrics
        m1 = metrics.mean(axis=0).tolist() + ['region', region_str]
        m2 = metrics.std(axis=0).tolist() + ['eras', nera]
        m3 = metrics.min(axis=0).tolist() + ['sharpe', sharpe]
        m4 = metrics.max(axis=0).tolist() + ['consis', consis]
        data = [m1, m2, m3, m4]

        # make dataframe
        columns = metrics.columns.tolist() + ['stats', '']
        df = pd.DataFrame(data=data,
                          index=['mean', 'std', 'min', 'max'],
                          columns=columns)

        return df

    def copy(self):
        "Copy of prediction"
        if self.df is None:
            return Prediction(None)
        # df.copy(deep=True) doesn't copy index. So:
        df = self.df
        df = pd.DataFrame(df.values.copy(),
                          df.index.copy(deep=True),
                          df.columns.copy())
        return Prediction(df)

    @property
    def size(self):
        if self.df is None:
            return 0
        return self.df.size

    @property
    def shape(self):
        if self.df is None:
            return tuple()
        return self.df.shape

    def __len__(self):
        "Number of rows"
        if self.df is None:
            return 0
        return self.df.__len__()

    def column_list(self):
        "Return column names of dataframe as a list"
        return self.df.columns.tolist()

    def __add__(self, other_prediction):
        "Concatenate two prediction objects that have no overlap in ids"
        return concat_prediction([self, other_prediction])

    def __repr__(self):
        if self.df is None:
            return ''
        t = []
        fmt = '{:<10}{:>13.6f}'
        y = self.df.yhat
        t.append(fmt.format('mean', y.mean()))
        t.append(fmt.format('std', y.std()))
        t.append(fmt.format('min', y.min()))
        t.append(fmt.format('max', y.max()))
        t.append(fmt.format('rows', len(self.df)))
        t.append(fmt.format('nulls', y.isnull().sum()))
        return '\n'.join(t)


def load_prediction(file_path):
    "Load prediction object from hdf archive; return Prediction"
    df = pd.read_hdf(file_path, key=HDF_PREDICTION_KEY)
    return Prediction(df)


def concat_prediction(predictions):
    "Concatenate list-like of prediction objects; ids must not overlap"
    dfs = [d.df for d in predictions]
    try:
        df = pd.concat(dfs, verify_integrity=True, copy=True)
    except ValueError:
        # pandas doesn't raise expected IndexError and for our large data
        # object, the id overlaps that it prints can be very long so
        raise IndexError("Overlap in ids found")
    return Prediction(df)
