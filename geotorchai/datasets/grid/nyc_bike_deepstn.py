
import os
import torch
from torch.utils.data import Dataset
from geotorchai.utility.exceptions import InvalidParametersException
from geotorchai.utility._download_utils import _download_remote_file
import numpy as np


class BikeNYCDeepSTN(Dataset):
    '''
    This dataset is based on https://github.com/FIBLAB/DeepSTN/tree/master/BikeNYC/DATA
    Grid map_height and map_width = 21 and 12

    Parameters
    ..........
    root (String) - Path to the dataset if it is already downloaded. If not downloaded, it will be downloaded in the given path.
    download (Boolean, Optional) - Set to True if dataset is not available in the given directory. Default: False
    is_training_data (Boolean, Optional) - Set to True if you want to create the training dataset, False for testing dataset. Default: True
    test_ratio (Float, Optional) - Length fraction of the test dataset. Default: 0.1
    len_closeness (Int, Optional) - Length of closeness. Default: 3
    len_period (Int, Optional) - Length of period. Default: 4
    len_trend (Int, Optional) - Length of trend. Default: 4
    T_closeness (Int, Optional) - Closeness length of T_data. Default: 1
    T_period (Int, Optional) - Period length of T_data. Default: 24
    T_trend (Int, Optional) - Trend length of T_data. Default: 24*7
    normalize (Boolean, Optional) - If set to True, data will be normalized. Default: True
    '''

    DATA_URL = "https://raw.githubusercontent.com/FIBLAB/DeepSTN/master/BikeNYC/DATA/dataBikeNYC/flow_data.npy"
    POI_URL = "https://raw.githubusercontent.com/FIBLAB/DeepSTN/master/BikeNYC/DATA/dataBikeNYC/poi_data.npy"

    def __init__(self, root, download = False, len_closeness = 3, len_period = 4, len_trend = 4, T_closeness=1, T_period=24, T_trend=24*7, normalize=True):
        super().__init__()

        if download:
            _download_remote_file(self.DATA_URL, root)
            _download_remote_file(self.POI_URL, root)

        data_dir = self._get_path(root)

        flow_data = np.load(open(data_dir + "/flow_data.npy", "rb"))
        poi_data = np.load(open(data_dir + "/poi_data.npy", "rb"))

        self.full_data = np.copy(flow_data)

        max_data = np.max(self.full_data)
        min_data = np.min(self.full_data)
        self.min_max_diff = max_data - min_data
        if normalize:
            self.full_data = (2.0 * self.full_data - (max_data + min_data)) / (max_data - min_data)

        self._create_feature_vector(self.full_data, poi_data, len_closeness, len_period, len_trend, T_closeness, T_period, T_trend)

        self.use_lead_time = False
        self.sequential = False
        self.periodical = True



    ## This method returns the difference between maximum and minimum values of this dataset
    def get_min_max_difference(self):
        return self.min_max_diff


    def set_sequential_representation(self, history_length, prediction_length):
        '''
        Call this method if you want to iterate the dataset as a sequence of histories and predictions instead of closeness, period, and trend.

        Parameters
        ..........
        history_length (Int) - Length of history data in sequence of each sample
        prediction_length (Int) - Length of prediction data in sequence of each sample
        '''

        history_data = []
        predict_data = []
        total_length = self.full_data.shape[0]
        for end_idx in range(history_length + prediction_length, total_length):
            predict_frames = self.full_data[end_idx-prediction_length:end_idx]
            history_frames = self.full_data[end_idx-prediction_length-history_length:end_idx-prediction_length]
            history_data.append(history_frames)
            predict_data.append(predict_frames)
        history_data = np.stack(history_data)
        predict_data = np.stack(predict_data)

        self.X_data = torch.tensor(history_data)
        self.Y_data = torch.tensor(predict_data)

        self.use_lead_time = False
        self.sequential = True
        self.periodical = False


    def merge_closeness_period_trend(self, lead_time = 2*24):
        '''
        Call this method if you want to iterate the dataset as a sequence of histories and label where step difference sequence and label is lead_time

        Parameters
        ..........
        lead_time (Int, Optional) - Difference between input (history) and label (prediction). Default: 2*24
        '''

        self.lead_time_data = torch.tensor(self.full_data)
        self.lead_time = lead_time
        self.use_lead_time = True
        self.sequential = False
        self.periodical = False


    def __len__(self) -> int:
        if self.use_lead_time:
            return len(self.lead_time_data) - self.lead_time
        else:
            return len(self.Y_data)


    def __getitem__(self, index: int):

        if self.periodical:
            sample = {"x_closeness": self.X_closeness[index], \
                      "x_period": self.X_period[index], \
                      "x_trend": self.X_trend[index], \
                      "t_data": self.T_data[index], \
                      "p_data": self.P_data[index], \
                      "y_data": self.Y_data[index]}
        else:
            if self.use_lead_time:
                x_data = self.lead_time_data[index]
                y_data = self.lead_time_data[index + self.lead_time]
            else:
                x_data = self.X_data[index]
                y_data = self.Y_data[index]
            sample = {"x_data": x_data, "y_data": y_data}

        return sample


    def _get_path(self, root_dir):
        queue = [root_dir]
        while queue:
            data_dir = queue.pop(0)
            folders = os.listdir(data_dir)
            if "flow_data.npy" in folders and "poi_data.npy" in folders:
                return data_dir

            for folder in folders:
                if os.path.isdir(data_dir + "/" + folder):
                    queue.append(data_dir + "/" + folder)

        return None


    # This is replication of lzq_load_data method proposed by authors here: https://github.com/FIBLAB/DeepSTN/blob/master/BikeNYC/DATA/lzq_read_data_time_poi.py
    def _create_feature_vector(self, all_data, poi, len_closeness, len_period, len_trend, T_closeness, T_period, T_trend):
        len_total,feature,map_height,map_width = all_data.shape

        time=np.arange(len_total,dtype=int)
        time_hour=time%T_period
        matrix_hour=np.zeros([len_total,24,map_height,map_width])
        for i in range(len_total):
            matrix_hour[i,time_hour[i],:,:]=1

        time_day=(time//T_period)%7
        matrix_day=np.zeros([len_total,7,map_height,map_width])
        for i in range(len_total):
            matrix_day[i,time_day[i],:,:]=1

        matrix_T=np.concatenate((matrix_hour,matrix_day),axis=1)

        if len_trend>0:
            number_of_skip_hours=T_trend*len_trend
        elif len_period>0:
            number_of_skip_hours=T_period*len_period
        elif len_closeness>0:
            number_of_skip_hours=T_closeness*len_closeness
        else:
            raise InvalidParametersException("Wrong parameters")

        Y=all_data[number_of_skip_hours:len_total]

        if len_closeness>0:
            self.X_closeness=all_data[number_of_skip_hours-T_closeness:len_total-T_closeness]
            for i in range(len_closeness-1):
                self.X_closeness=np.concatenate((self.X_closeness,all_data[number_of_skip_hours-T_closeness*(2+i):len_total-T_closeness*(2+i)]),axis=1)
        if len_period>0:
            self.X_period=all_data[number_of_skip_hours-T_period:len_total-T_period]
            for i in range(len_period-1):
                self.X_period=np.concatenate((self.X_period,all_data[number_of_skip_hours-T_period*(2+i):len_total-T_period*(2+i)]),axis=1)
        if len_trend>0:
            self.X_trend=all_data[number_of_skip_hours-T_trend:len_total-T_trend]
            for i in range(len_trend-1):
                self.X_trend=np.concatenate((self.X_trend,all_data[number_of_skip_hours-T_trend*(2+i):len_total-T_trend*(2+i)]),axis=1)

        matrix_T=matrix_T[number_of_skip_hours:]

        self.T_data = matrix_T
        self.Y_data = Y

        len_data=self.X_closeness.shape[0]

        for i in range(poi.shape[0]):
            poi[i]=poi[i]/np.max(poi[i])
        self.P_data=np.repeat(poi.reshape(1,poi.shape[0],map_height,map_width),len_data,axis=0)

        self.X_closeness = torch.tensor(self.X_closeness)
        self.X_period = torch.tensor(self.X_period)
        self.X_trend = torch.tensor(self.X_trend)
        self.T_data = torch.tensor(self.T_data)
        self.P_data = torch.tensor(self.P_data)
        self.Y_data = torch.tensor(self.Y_data)

