import os
import numpy as np
import torch
from torch.utils.data import DataLoader
from torch.utils.data.sampler import SubsetRandomSampler
import torch.nn as nn
from geotorchai.models.grid import STResNet
from geotorchai.datasets.grid import BikeNYCDeepSTN


len_closeness = 3
len_period = 4
len_trend = 4
nb_residual_unit = 4

map_height, map_width = 21, 12
nb_flow = 2
T = 24

epoch_nums = 100
learning_rate = 0.0002
batch_size = 32
params = {'batch_size': batch_size, 'shuffle': False}

validation_ratio = 0.1
test_ratio = 0.1

out_dir = 'reports'
checkpoint_dir = out_dir+'/checkpoint'
model_name = 'stresnet'
model_dir = checkpoint_dir + "/" + model_name
os.makedirs(model_dir, exist_ok=True)

initial_checkpoint = model_dir + '/model.best.pth'
LOAD_INITIAL = False


def createModelAndTrain():

    full_dataset = BikeNYCDeepSTN(root = "data/deepstn")
    min_max_diff = full_dataset.get_min_max_difference()

    dataset_size = len(full_dataset)
    indices = list(range(dataset_size))
    val_split = int(np.floor((1 - (validation_ratio + test_ratio)) * dataset_size))
    test_split = int(np.floor((1 - test_ratio) * dataset_size))
    train_indices, val_indices, test_indices = indices[:val_split], indices[val_split:test_split], indices[test_split:]

    train_sampler = SubsetRandomSampler(train_indices)
    valid_sampler = SubsetRandomSampler(val_indices)
    test_sampler = SubsetRandomSampler(test_indices)

    training_generator = DataLoader(full_dataset, **params, sampler=train_sampler)
    val_generator = DataLoader(full_dataset, **params, sampler=valid_sampler)
    test_generator = DataLoader(full_dataset, **params, sampler=test_sampler)

    if torch.cuda.is_available():
        device = torch.device("cuda")
    elif torch.backends.mps.is_available():
        device = torch.device("mps")
    else:
        device = torch.device("cpu")

    # Total iterations
    total_iters = 5

    test_mae = []
    test_mse = []
    test_rmse = []

    for iteration in range(total_iters):
        model = STResNet((len_closeness, nb_flow, map_height, map_width),
                     (len_period, nb_flow, map_height, map_width),
                     (len_trend, nb_flow , map_height, map_width),
                     external_dim = None, nb_residual_unit = nb_residual_unit)

        if LOAD_INITIAL:
            model.load_state_dict(torch.load(initial_checkpoint, map_location=lambda storage, loc: storage))

        loss_fn = nn.MSELoss()
        optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
        model.to(device)
        loss_fn.to(device)

        min_val_loss = None
        for e in range(epoch_nums):
            for i, sample in enumerate(training_generator):
                X_c = sample["x_closeness"].type(torch.FloatTensor).to(device)
                X_p = sample["x_period"].type(torch.FloatTensor).to(device)
                X_t = sample["x_trend"].type(torch.FloatTensor).to(device)
                Y_batch = sample["y_data"].type(torch.FloatTensor).to(device)

                # Forward pass
                outputs = model(X_c, X_p, X_t)
                loss = loss_fn(outputs, Y_batch)

                # Backward and optimize
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

            print('Epoch [{}/{}], Loss: {:.4f}'.format(e + 1, epoch_nums, loss.item()))

            val_loss = get_validation_loss(model, val_generator, loss_fn, device)
            print('Mean validation loss:', val_loss)

            if min_val_loss == None or val_loss < min_val_loss:
                min_val_loss = val_loss
                torch.save(model.state_dict(), initial_checkpoint)
                print('best model saved!')

        model.load_state_dict(torch.load(initial_checkpoint, map_location=lambda storage, loc: storage))

        rmse_list=[]
        mse_list=[]
        mae_list=[]
        for i, sample in enumerate(test_generator):
            X_c = sample["x_closeness"].type(torch.FloatTensor).to(device)
            X_p = sample["x_period"].type(torch.FloatTensor).to(device)
            X_t = sample["x_trend"].type(torch.FloatTensor).to(device)
            Y_batch = sample["y_data"].type(torch.FloatTensor).to(device)

            outputs = model(X_c, X_p, X_t)
            mse, mae, rmse = compute_errors(outputs.cpu().data.numpy(), Y_batch.cpu().data.numpy())

            rmse_list.append(rmse)
            mse_list.append(mse)
            mae_list.append(mae)

        rmse = np.mean(rmse_list)
        mse = np.mean(mse_list)
        mae = np.mean(mae_list)

        print("Iteration:", iteration)
        print('Test mse: %.6f mae: %.6f rmse (norm): %.6f, mae (real): %.6f, rmse (real): %.6f' % (mse, mae, rmse, mae * min_max_diff/2, rmse*min_max_diff/2))

        test_mae.append(mae)
        test_mse.append(mse)
        test_rmse.append(rmse)

    print("\n************************")
    print("Test ST-ResNet model with BikeNYCDeepSTN Dataset:")
    print("train and test finished")
    for i in range(total_iters):
        print("Iteration: {0}, MAE: {1}, RMSE: {2}, Real MAE: {3}, Real RMSE: {4}".format(i, test_mae[i], test_rmse[i], test_mae[i]*min_max_diff/2, test_rmse[i]*min_max_diff/2))

    test_mae_mean = np.mean(test_mae)
    test_rmse_mean = np.mean(test_rmse)

    print("\nMean MAE: {0}, Mean Real MAE: {1}".format(test_mae_mean, test_mae_mean*min_max_diff/2))
    print("Mean RMSE: {0}, Mean Real RMSE: {1}".format(test_rmse_mean, test_rmse_mean * min_max_diff/2))


def compute_errors(preds, y_true):
    pred_mean = preds[:, 0:2]
    diff = y_true - pred_mean

    mse = np.mean(diff ** 2)
    rmse = np.sqrt(mse)
    mae = np.mean(np.abs(diff))

    return mse, mae, rmse


def get_validation_loss(model, val_generator, criterion, device):
    model.eval()
    mean_loss = []
    for i, sample in enumerate(val_generator):
        X_c = sample["x_closeness"].type(torch.FloatTensor).to(device)
        X_p = sample["x_period"].type(torch.FloatTensor).to(device)
        X_t = sample["x_trend"].type(torch.FloatTensor).to(device)
        Y_batch = sample["y_data"].type(torch.FloatTensor).to(device)

        outputs = model(X_c, X_p, X_t)
        mse= criterion(outputs, Y_batch).item()
        mean_loss.append(mse)

    mean_loss = np.mean(mean_loss)
    return mean_loss



if __name__ == '__main__':

    createModelAndTrain()



