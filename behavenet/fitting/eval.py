"""Utility functions for evaluating model fits."""

import numpy as np
from behavenet.fitting.utils import get_best_model_and_data


def export_latents(data_generator, model, filename=None):
    """Export predicted latents using an already initialized data_generator and model.

    Latents are saved based on the model's hparams dict unless another file is provided. The
    default filename is `[lab_id]_[expt_id]_[animal_id]_[session_id]_latents.pkl`.

    Parameters
    ----------
    data_generator : :obj:`ConcatSessionGenerator` object
        data generator to use for latent creation
    model : :obj:`AE` object
        pytorch model
    filename : :obj:`str` or :obj:`NoneType`, optional
        absolute path to save latents; if :obj:`NoneType`, latents are stored in model directory

    """

    import pickle
    import os

    model.eval()

    # initialize container for latents
    latents = [[] for _ in range(data_generator.n_datasets)]
    for sess, dataset in enumerate(data_generator.datasets):
        latents[sess] = [np.array([]) for _ in range(dataset.n_trials)]

    # partially fill container (gap trials will be included as nans)
    dtypes = ['train', 'val', 'test']
    for dtype in dtypes:
        data_generator.reset_iterators(dtype)
        for i in range(data_generator.n_tot_batches[dtype]):
            data, sess = data_generator.next_batch(dtype)

            if next(model.parameters()).is_cuda:
                data = {key: val.to('cuda') for key, val in data.items()}

            # process batch, perhaps in chunks if full batch is too large to fit on gpu
            chunk_size = 200
            y = data['images'][0]
            batch_size = y.shape[0]
            if batch_size > chunk_size:
                latents[sess][data['batch_idx'].item()] = np.full(
                    shape=(data['images'].shape[1], model.hparams['n_ae_latents']),
                    fill_value=np.nan)
                # split into chunks
                n_chunks = int(np.ceil(batch_size / chunk_size))
                for chunk in range(n_chunks):
                    # take chunks of size chunk_size, plus overlap due to
                    # max_lags
                    idx_beg = chunk * chunk_size
                    idx_end = np.min([(chunk + 1) * chunk_size, batch_size])
                    curr_latents, _, _ = model.encoding(y[idx_beg:idx_end], dataset=sess)
                    latents[sess][data['batch_idx'].item()][idx_beg:idx_end, :] = \
                        curr_latents.cpu().detach().numpy()
            else:
                curr_latents, _, _ = model.encoding(y, dataset=sess)
                latents[sess][data['batch_idx'].item()] = curr_latents.cpu().detach().numpy()

    # save latents separately for each dataset
    for sess, dataset in enumerate(data_generator.datasets):
        if filename is None:
            # get save name which includes lab/expt/animal/session
            sess_id = str('%s_%s_%s_%s_latents.pkl' % (
                dataset.lab, dataset.expt, dataset.animal, dataset.session))
            filename = os.path.join(
                model.hparams['expt_dir'], 'version_%i' % model.version, sess_id)
        # save out array in pickle file
        print('saving latents %i of %i:\n%s' % (sess + 1, data_generator.n_datasets, filename))
        latents_dict = {'latents': latents[sess], 'trials': dataset.batch_idxs}
        with open(filename, 'wb') as f:
            pickle.dump(latents_dict, f)


def export_states(hparams, data_generator, model, filename=None):
    """Export predicted latents using an already initialized data_generator and model.

    States are saved based on the hparams dict unless another file is provided. The default
    filename is `[lab_id]_[expt_id]_[animal_id]_[session_id]_states.pkl`.

    Parameters
    ----------
    hparams : :obj:`dict`
        needs to contain 'expt_dir' and 'version'
    data_generator : :obj:`ConcatSessionGenerator` object
        data generator to use for latent creation
    model : :obj:`HMM` object
        ssm model
    filename : :obj:`str` or :obj:`NoneType`, optional
        absolute path to save latents; if :obj:`NoneType`, latents are stored in model directory

    """

    import pickle
    import os

    # initialize container for states
    states = [[] for _ in range(data_generator.n_datasets)]
    for sess, dataset in enumerate(data_generator.datasets):
        states[sess] = [np.array([]) for _ in range(dataset.n_trials)]

    # partially fill container (gap trials will be included as nans)
    dtypes = ['train', 'val', 'test']
    for dtype in dtypes:
        data_generator.reset_iterators(dtype)
        for i in range(data_generator.n_tot_batches[dtype]):
            data, sess = data_generator.next_batch(dtype)

            # process batch
            if hparams['model_class'].find('label') > -1:
                y = data['labels'][0][0]
            else:
                y = data['ae_latents'][0][0]
            batch_size = y.shape[0]

            curr_states = model.most_likely_states(y)

            states[sess][data['batch_idx'].item()] = curr_states

    # save states separately for each dataset
    for sess, dataset in enumerate(data_generator.datasets):
        if filename is None:
            # get save name which includes lab/expt/animal/session
            sess_id = str('%s_%s_%s_%s_states.pkl' % (
                dataset.lab, dataset.expt, dataset.animal, dataset.session))
            filename = os.path.join(
                hparams['expt_dir'], 'version_%i' % hparams['version'], sess_id)
        # save out array in pickle file
        print('saving states %i of %i:\n%s' % (sess + 1, data_generator.n_datasets, filename))
        states_dict = {'states': states[sess], 'trials': dataset.batch_idxs}
        with open(filename, 'wb') as f:
            pickle.dump(states_dict, f)


def export_predictions(data_generator, model, filename=None):
    """Export decoder predictions using an already initialized data_generator and model.

    Predictions are saved based on the model's hparams dict unless another file is provided. The
    default filename is `[lab_id]_[expt_id]_[animal_id]_[session_id]_predictions.pkl`.

    This function only supports pytorch decoding models - not autoencoders. To get AE
    reconstructions see the `get_reconstruction` function in this module.

    Parameters
    ----------
    data_generator : :obj:`ConcatSessionGenerator` object
        data generator to use for latent creation
    model : :obj:`NN` object
        pytorch model
    filename : :obj:`str` or :obj:`NoneType`, optional
        absolute path to save latents; if :obj:`NoneType`, latents are stored in model directory

    """

    import pickle
    import os

    model.eval()

    # initialize container for latents
    predictions = [[] for _ in range(data_generator.n_datasets)]
    for sess, dataset in enumerate(data_generator.datasets):
        predictions[sess] = [np.array([]) for _ in range(dataset.n_trials)]

    # partially fill container (gap trials will be included as nans)
    max_lags = model.hparams['n_max_lags']
    dtypes = ['train', 'val', 'test']
    for dtype in dtypes:
        data_generator.reset_iterators(dtype)
        for i in range(data_generator.n_tot_batches[dtype]):
            data, sess = data_generator.next_batch(dtype)

            if next(model.parameters()).is_cuda:
                data = {key: val.to('cuda') for key, val in data.items()}

            predictors = data[model.hparams['input_signal']][0]
            targets = data[model.hparams['output_signal']][0]

            trial_len = targets.shape[0]
            predictions[sess][data['batch_idx'].item()] = np.full(
                shape=(trial_len, model.hparams['output_size']), fill_value=np.nan)

            # process batch, perhaps in chunks if full batch is too large
            # to fit on gpu
            chunk_size = 200
            batch_size = targets.shape[0]
            if batch_size > chunk_size:
                # split into chunks
                n_chunks = int(np.ceil(batch_size / chunk_size))
                for chunk in range(n_chunks):
                    # take chunks of size chunk_size, plus overlap due to
                    # max_lags
                    idx_beg = np.max([chunk * chunk_size - max_lags, 0])
                    idx_end = np.min([(chunk + 1) * chunk_size + max_lags, batch_size])
                    outputs, _ = model(predictors[idx_beg:idx_end])
                    slc = (idx_beg + max_lags, idx_end - max_lags)
                    predictions[sess][data['batch_idx'].item()][slice(*slc), :] = \
                        outputs[max_lags:-max_lags].cpu().detach().numpy()
            else:
                outputs, _ = model(predictors)
                slc = (max_lags, -max_lags)

                predictions[sess][data['batch_idx'].item()][slice(*slc), :] = \
                    outputs[max_lags:-max_lags].cpu().detach().numpy()

    # save latents separately for each dataset
    for sess, dataset in enumerate(data_generator.datasets):
        if filename is None:
            # get save name which includes lab/expt/animal/session
            sess_id = str('%s_%s_%s_%s_predictions.pkl' % (
                dataset.lab, dataset.expt, dataset.animal, dataset.session))

            filename = os.path.join(
                model.hparams['expt_dir'], 'version_%i' % model.version, sess_id)
        # save out array in pickle file
        print('saving latents %i of %i to %s' % (sess + 1, data_generator.n_datasets, filename))
        predictions_dict = {'predictions': predictions[sess], 'trials': dataset.batch_idxs}
        with open(filename, 'wb') as f:
            pickle.dump(predictions_dict, f)


def export_latents_best(hparams, filename=None, export_all=False):
    """Export predictions for the best decoding model in a test tube experiment.

    Predictions are saved in the corresponding model directory.

    Parameters
    ----------
    hparams : :obj:`dict`
        needs to contain enough information to specify an autoencoder
    filename : :obj:`str` or :obj:`NoneType`, optional
        absolute path to save latents; if :obj:`NoneType`, latents are stored in model directory
    export_all : :obj:`bool`, optional
        :obj:`True` to export latents for train, val, test, and gap trials

    """
    from behavenet.models import AE
    if export_all:
        data_kwargs = dict(trial_splits=dict(train_tr=1, val_tr=0, test_tr=0, gap_tr=0))
    else:
        data_kwargs = {}
    model, data_generator = get_best_model_and_data(hparams, AE, data_kwargs=data_kwargs)
    export_latents(data_generator, model, filename=filename)


def export_predictions_best(hparams, filename=None, export_all=False):
    """Export predictions for the best decoding model in a test tube experiment.

    Predictions are saved in the corresponding model directory.

    Parameters
    ----------
    hparams : :obj:`dict`
        needs to contain enough information to specify an autoencoder
    filename : :obj:`str` or :obj:`NoneType`, optional
        absolute path to save latents; if :obj:`NoneType`, latents are stored in model directory
    export_all : :obj:`bool`, optional
        :obj:`True` to export latents for train, val, test, and gap trials

    """

    from behavenet.models import Decoder
    if export_all:
        data_kwargs = dict(trial_splits=dict(train_tr=1, val_tr=0, test_tr=0, gap_tr=0))
    else:
        data_kwargs = {}
    model, data_generator = get_best_model_and_data(hparams, Decoder, data_kwargs=data_kwargs)
    export_predictions(data_generator, model, filename=filename)


def get_reconstruction(model, inputs, dataset=None, return_latents=False):
    """Reconstruct an image from either image or latent inputs.

    Parameters
    ----------
    model : :obj:`AE` object
        pytorch model
    inputs : :obj:`torch.Tensor` object
        - image tensor of shape (batch, channels, y_pix, x_pix)
        - latents tensor of shape (batch, n_ae_latents)
    dataset : :obj:`int` or :obj:`NoneType`, optional
        for use with session-specific io layers
    return_latents : :obj:`bool`, optional
        if :obj:`True` return tuple of (recon, latents)

    Returns
    -------
    :obj:`np.ndarray`
        reconstructed images of shape (batch, channels, y_pix, x_pix)

    """
    import torch

    if not isinstance(inputs, torch.Tensor):
        inputs = torch.Tensor(inputs)

    # check to see if inputs are images or latents
    if len(inputs.shape) == 2:
        input_type = 'latents'
    else:
        input_type = 'images'

    if input_type == 'images':
        ims_recon, latents = model(inputs, dataset=dataset)
    else:
        # TODO: how to incorporate maxpool layers for decoding only?
        ims_recon = model.decoding(inputs, None, None, dataset=None)
        latents = inputs
    ims_recon = ims_recon.cpu().detach().numpy()
    latents = latents.cpu().detach().numpy()

    if return_latents:
        return ims_recon, latents
    else:
        return ims_recon


def get_test_metric(hparams, model_version, metric='r2', sess_idx=0):
    """Calculate a single R\ :sup:`2` value across all test batches for a decoder.

    Parameters
    ----------
    hparams : :obj:`dict`
        needs to contain enough information to specify an autoencoder
    model_version : :obj:`int` or :obj:`str`
        version from test tube experiment defined in :obj:`hparams` or the string 'best'
    metric : :obj:`str`, optional
        'r2' | 'fc'
    sess_idx : :obj:`int`, optional
        session index into data generator

    Returns
    -------
    :obj:`tuple`
        - hparams (:obj:`dict`): hparams of model used to calculate metrics
        - metric (:obj:`int`)

    """

    from sklearn.metrics import r2_score, accuracy_score
    from behavenet.fitting.utils import get_best_model_and_data
    from behavenet.models import Decoder

    model, data_generator = get_best_model_and_data(
        hparams, Decoder, load_data=True, version=model_version)

    n_test_batches = len(data_generator.datasets[sess_idx].batch_idxs['test'])
    max_lags = hparams['n_max_lags']
    true = []
    pred = []
    data_generator.reset_iterators('test')
    for i in range(n_test_batches):
        batch, _ = data_generator.next_batch('test')

        # get true latents/states
        if metric == 'r2':
            curr_true = batch['ae_latents'][0].cpu().detach().numpy()
        elif metric == 'fc':
            curr_true = batch['arhmm_states'][0].cpu().detach().numpy()
        else:
            raise ValueError('"%s" is an invalid metric type' % metric)

        # get predicted latents
        curr_pred = model(batch['neural'][0])[0].cpu().detach().numpy()

        true.append(curr_true[max_lags:-max_lags])
        pred.append(curr_pred[max_lags:-max_lags])

    if metric == 'r2':
        metric = r2_score(
            np.concatenate(true, axis=0), np.concatenate(pred, axis=0),
            multioutput='variance_weighted')
    elif metric == 'fc':
        metric = accuracy_score(
            np.concatenate(true, axis=0), np.argmax(np.concatenate(pred, axis=0), axis=1))

    return model.hparams, metric


def export_train_plots(hparams, dtype, loss_type='mse', save_file=None, format='png'):
    """Export plot with MSE/LL as a function of training epochs.

    Parameters
    ----------
    hparams : :obj:`dict`
        needs to contain enough information to specify the desired model (autoencoder, arhmm, etc.)
    dtype : :obj:`str`
        type of trials to use for plotting: 'train' | 'val' (metrics are not computed for 'test'
        trials throughout training)
    loss_type : :obj:`str`, optional
        'mse' | 'll'
    save_file : :obj:`str` or :obj:`NoneType`, optional
        full filename (absolute path) for saving plot; if :obj:`NoneType`, plot is displayed
    format : :obj:`str`
        file format of plot, e.g. 'png' | 'pdf' | 'jpeg'

    """
    import os
    import pandas as pd
    import seaborn as sns
    import matplotlib.pyplot as plt
    from behavenet.fitting.utils import read_session_info_from_csv

    sns.set_style('white')
    sns.set_context('talk')

    # find metrics csv file
    version_dir = os.path.join(hparams['expt_dir'], 'version_%i' % hparams['version'])
    metric_file = os.path.join(version_dir, 'metrics.csv')
    metrics = pd.read_csv(metric_file)

    # collect data from csv file
    sess_ids = read_session_info_from_csv(os.path.join(version_dir, 'session_info.csv'))
    sess_ids_strs = []
    for sess_id in sess_ids:
        sess_ids_strs.append(str('%s/%s' % (sess_id['animal'], sess_id['session'])))
    metrics_df = []
    for i, row in metrics.iterrows():
        dataset = 'all' if row['dataset'] == -1 else sess_ids_strs[row['dataset']]
        metrics_df.append(pd.DataFrame({
            'dataset': dataset,
            'epoch': row['epoch'],
            'loss': row['val_loss'],
            'dtype': 'val',
        }, index=[0]))
        metrics_df.append(pd.DataFrame({
            'dataset': dataset,
            'epoch': row['epoch'],
            'loss': row['tr_loss'],
            'dtype': 'train',
        }, index=[0]))
    metrics_df = pd.concat(metrics_df)

    # plot data
    data_queried = metrics_df[
        (metrics_df.dtype == dtype) &
        (metrics_df.epoch > 0) &
        ~pd.isna(metrics_df.loss)]
    splt = sns.relplot(x='epoch', y='loss', hue='dataset', kind='line', data=data_queried)
    splt.ax.set_xlabel('Epoch')
    if loss_type == 'mse':
        splt.ax.set_yscale('log')
        splt.ax.set_ylabel('MSE per pixel')
    elif loss_type == 'll':
        splt.ax.set_ylabel('Neg log prob per datapoint')
    else:
        raise ValueError('"%s" is an invalid loss type' % loss_type)
    title_str = 'Validation' if dtype == 'val' else 'Training'
    plt.title('%s loss' % title_str)

    if save_file is not None:
        plt.savefig(str('%s.%s' % (save_file, format)), dpi=300, format=format)
        plt.close()
    else:
        plt.show()

    return splt
