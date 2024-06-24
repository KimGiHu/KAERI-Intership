import numpy as np
import matplotlib.pyplot as plt
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, Dataset
from sklearn.preprocessing import MinMaxScaler,StandardScaler
import random

# 시드 값 설정
seed = 42

# 기본 시드 고정
random.seed(seed)
np.random.seed(seed)
torch.manual_seed(seed)

# CUDA 사용 시 추가 설정
if torch.cuda.is_available():
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)  # 멀티-GPU 사용 시
    # CuDNN 결정론적 및 비결정론적 동작 설정
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False

class CustomDataset(Dataset):
    def __init__(self, data, labels):
        self.data = data
        self.labels = labels
    def __len__(self):
        return len(self.data)
    def __getitem__(self, idx):
        return self.data[idx], self.labels[idx]

# CVAE 모델 정의
class Encoder(nn.Module):
    def __init__(self, input_dim, seq_len, latent_dim, condition_dim, dropout_prob=0.2):
        super(Encoder, self).__init__()
        self.conv1 = nn.Conv1d(input_dim, 128, kernel_size=12, padding=6)
        self.bn1 = nn.BatchNorm1d(num_features=128)
        self.pool1 = nn.MaxPool1d(kernel_size=2, stride=2)
        self.conv1_dropout = nn.Dropout(p=dropout_prob)

        self.conv2 = nn.Conv1d(128, 128, kernel_size=12, padding=6)
        self.bn2 = nn.BatchNorm1d(num_features=128)
        self.pool2 = nn.MaxPool1d(kernel_size=2, stride=2)
        self.conv2_dropout = nn.Dropout(p=dropout_prob)

        self.conv3 = nn.Conv1d(128, 128, kernel_size=12, padding=6)
        self.bn3 = nn.BatchNorm1d(num_features=128)
        self.pool3 = nn.MaxPool1d(kernel_size=2, stride=2)
        self.conv3_dropout = nn.Dropout(p=dropout_prob)

        def calc_seq_len(seq_len):
            seq_len = (seq_len + 2 * 6 - 12) // 1 + 1  # conv1
            seq_len = (seq_len - 2) // 2 + 1           # pool1
            seq_len = (seq_len + 2 * 6 - 12) // 1 + 1  # conv2
            seq_len = (seq_len - 2) // 2 + 1           # pool2
            seq_len = (seq_len + 2 * 6 - 12) // 1 + 1  # conv3
            seq_len = (seq_len - 2) // 2 + 1           # pool3
            return seq_len

        self.seq_len = calc_seq_len(seq_len)
        # self.fc = nn.Linear(128 * self.seq_len + condition_dim, 512)
        self.fc = nn.Linear(128 * self.seq_len, 512)
        self.fc_mu = nn.Linear(512 + condition_dim, latent_dim)
        self.fc_logvar = nn.Linear(512 + condition_dim, latent_dim)
        self.dropout = nn.Dropout(p=dropout_prob)
        self.bn0 = nn.BatchNorm1d(num_features=(512 + condition_dim))

    def forward(self, x, c):
        # CNN Block1
        x = self.conv1(x)
        x = self.bn1(x)
        x = self.pool1(x)
        x = torch.relu(x)
        x = self.conv1_dropout(x)
        
        # CNN Block2
        x = self.conv2(x)
        x = self.bn2(x)
        x = self.pool2(x)
        x = torch.relu(x)
        x = self.conv2_dropout(x)
        
        # CNN Block3
        x = self.conv3(x)
        x = self.bn3(x)
        x = self.pool3(x)
        x = torch.relu(x)
        x = self.conv3_dropout(x)
        
        # Flatten 효과
        x = x.view(x.size(0), -1) 
        x = self.fc(x)

        x = torch.cat([x, c], dim=-1) 
        
        x = self.bn0(x)
        x = torch.relu(x)
        x = self.dropout(x)
        
        mu = self.fc_mu(x)
        logvar = self.fc_logvar(x)
        return mu, logvar

class Decoder(nn.Module):
    def __init__(self, latent_dim, seq_len, output_dim, condition_dim, dropout_prob=0.2):
        super(Decoder, self).__init__()
        self.fc1 = nn.Linear(latent_dim + condition_dim, 512)
        self.fc2 = nn.Linear(512, 128 * seq_len)
        self.dropout = nn.Dropout(p=dropout_prob)
        self.bn0 = nn.BatchNorm1d(num_features=128)

        self.up1 = nn.Upsample(scale_factor=2)
        self.bn1 = nn.BatchNorm1d(num_features=128)
        self.trans_conv1 = nn.ConvTranspose1d(128, 128, kernel_size=12, padding=6)
        self.conv1_dropout = nn.Dropout(p=dropout_prob)

        self.up2 = nn.Upsample(scale_factor=2)
        self.bn2 = nn.BatchNorm1d(num_features=128)
        self.trans_conv2 = nn.ConvTranspose1d(128, 128, kernel_size=12, padding=6)
        self.conv2_dropout = nn.Dropout(p=dropout_prob)

        self.up3 = nn.Upsample(size=4501)
        self.bn3 = nn.BatchNorm1d(num_features=128)
        self.trans_conv3 = nn.ConvTranspose1d(128, output_dim, kernel_size=12, padding=6)
        self.conv3_dropout = nn.Dropout(p=dropout_prob)

    def forward(self, z, c):
        z = torch.cat([z, c], dim=-1)   

        h = ((self.fc1(z)))
        h = ((self.fc2(h)))
        h = h.view(h.size(0), 128, -1)
        h = self.bn0(h)
        h = self.dropout(torch.relu(h))
        
        h = self.up1(h)
        h = self.bn1(h)
        h = (self.conv1_dropout(torch.relu(self.trans_conv1(h))))
        
        h = self.up2(h)
        h = self.bn2(h)
        h = (self.conv2_dropout(torch.relu(self.trans_conv2(h))))
        
        h = self.up3(h)
        h = self.bn3(h)
        x_recon = self.conv3_dropout(torch.sigmoid(self.trans_conv3(h)))
        return x_recon
    
class CVAE(nn.Module):
    def __init__(self, input_dim, seq_len, latent_dim, condition_dim, dropout_prob=0.2):
        super(CVAE, self).__init__()
        self.encoder = Encoder(input_dim, seq_len, latent_dim, condition_dim, dropout_prob)
        self.decoder = Decoder(latent_dim, self.encoder.seq_len, input_dim, condition_dim, dropout_prob)

    def reparameterize(self, mu, logvar):
        std = torch.exp(0.5 * logvar)
        eps = torch.randn_like(std)
        return mu + eps * std

    def forward(self, x, c):

        mu, logvar = self.encoder(x, c)
        z = self.reparameterize(mu, logvar)
        x_recon = self.decoder(z, c)
        return x_recon, mu, logvar

# 손실 함수 정의
def loss_function(x_recon, x, mu, logvar):
    BCE = nn.functional.mse_loss(x_recon, x, reduction='sum')
    KLD = -0.5 * torch.sum(1 + logvar - mu.pow(2) - logvar.exp()+ 1e-8)
    return BCE + 1*KLD

# 고유 파형들 정의
features=['A+IGBT-I', 'A+*IGBT-I', 'B+IGBT-I', 'B+*IGBT-I', 'C+IGBT-I', 
          'C+*IGBT-I', 'A-FLUX', 'B-FLUX', 'C-FLUX', 'CB-I','CB-V',
          'MOD-V', 'MOD-I','DV/DT']

system1='RFQ'     # pick a system to load and plot. Choose RFQ
system2='DTL'     # pick a system to load and plot. Choose DTL
system3='CCL'     # pick a system to load and plot. Choose CCL
system4='SCL'     # pick a system to load and plot. Choose SCL

# 데이터 로드 및 라벨 인코딩
def load_data(system):
    X = np.load(f'./hvcm/data/hvcm/{system}.npy')
    Y = np.load(f'./hvcm/data/hvcm/{system}_labels.npy', allow_pickle=True)
    return X, Y

X1, Y1 = load_data(system1)
X2, Y2 = load_data(system2)
X3, Y3 = load_data(system3)
X4, Y4 = load_data(system4)

time = np.arange(X1.shape[1]) * 400e-9 # 타임스텝 : 1.8ms (4500개 샘플씩, 한 샘플당 400ns)

# 시스템 인덱스 생성
system_indices = {
    system1: 0,
    system2: 1,
    system3: 2,
    system4: 3
}

def create_labels(Y, system):
    labels = np.array([system_indices[system]] * len(Y))
    return labels

labels1 = create_labels(Y1, system1)
labels2 = create_labels(Y2, system2)
labels3 = create_labels(Y3, system3)
labels4 = create_labels(Y4, system4)

# 배열 X,Y의 정상 및 오류 데이터들을 분리함
fault_indices_RFQ, normal_indices_RFQ = np.where(Y1[:,1] == 'Fault')[0], np.where(Y1[:,1] == 'Run')[0] 
fault_indices_DTL, normal_indices_DTL = np.where(Y2[:,1] == 'Fault')[0], np.where(Y2[:,1] == 'Run')[0]
fault_indices_CCL, normal_indices_CCL = np.where(Y3[:,1] == 'Fault')[0], np.where(Y3[:,1] == 'Run')[0]
fault_indices_SCL, normal_indices_SCL = np.where(Y4[:,1] == 'Fault')[0], np.where(Y4[:,1] == 'Run')[0]

Xnormal_RFQ, Xanomaly_RFQ = X1[normal_indices_RFQ,:,:], X1[fault_indices_RFQ,:,:]
Xnormal_DTL, Xanomaly_DTL = X2[normal_indices_DTL,:,:], X2[fault_indices_DTL,:,:]
Xnormal_CCL, Xanomaly_CCL = X3[normal_indices_CCL,:,:], X3[fault_indices_CCL,:,:]
Xnormal_SCL, Xanomaly_SCL = X4[normal_indices_SCL,:,:], X4[fault_indices_SCL,:,:]

Ynormal_RFQ, Yanomaly_RFQ = Y1[normal_indices_RFQ,:], Y1[fault_indices_RFQ,:]
Ynormal_DTL, Yanomaly_DTL = Y2[normal_indices_DTL,:], Y2[fault_indices_DTL,:]
Ynormal_CCL, Yanomaly_CCL = Y3[normal_indices_CCL,:], Y3[fault_indices_CCL,:]
Ynormal_SCL, Yanomaly_SCL = Y4[normal_indices_SCL,:], Y4[fault_indices_SCL,:]

# 정상,비정상 신호 concatenate
Xnormal_concat = np.concatenate( (Xnormal_RFQ, Xnormal_DTL, Xnormal_CCL, Xnormal_SCL), axis=0 )
Xanomaly_concat = np.concatenate( (Xanomaly_RFQ, Xanomaly_DTL, Xanomaly_CCL, Xanomaly_SCL), axis=0 )

# 원-핫 인코딩
labels_concat = np.concatenate((labels1[normal_indices_RFQ[:524]], labels2[normal_indices_DTL[:524]], labels3[normal_indices_CCL[:524]], labels4[normal_indices_SCL[:524]]), axis=0)
labels_one_hot = np.eye(len(system_indices))[labels_concat]

# 정규화(Standardized) 스케일러 인스턴스 초기화
standard = StandardScaler()
standard_IGBT = StandardScaler()
standard_FLUX = StandardScaler()
standard_CAP = StandardScaler()
standard_MOD = StandardScaler()

# Min-Max 스케일러- 파형별 ㄴ인스턴스 초기화
scaler_IGBT = MinMaxScaler()
scaler_FLUX = MinMaxScaler()
scaler_CAP = MinMaxScaler()
scaler_MOD = MinMaxScaler()

Xnormal_concat = np.concatenate( (Xnormal_RFQ[:524,:,:], Xnormal_DTL[:524,:,:], Xnormal_CCL[:524,:,:], Xnormal_SCL[:524,:,:]), axis=0 )
Xnormal_concat_tmp = np.array(Xnormal_concat)
Xnormal_concat = np.array(Xnormal_concat)

print(Xnormal_concat[524*0:524*0+1, :, 6]) # 오리지날 신호 확인

avg_RFQ_Xnormal = np.zeros(Xnormal_RFQ[:1,:,:].shape)
print(avg_RFQ_Xnormal.shape)

avg_RFQ_Xnormal = Xnormal_RFQ[:1,:,:]
print(avg_RFQ_Xnormal.shape)

for i in range(1,524):
    avg_RFQ_Xnormal += Xnormal_RFQ[i,:,:]
for i in range(0,14):
    avg_RFQ_Xnormal[:,:,i] = avg_RFQ_Xnormal[:,:,i] / 524
print(avg_RFQ_Xnormal)
avg_RFQ_Xnormal_plot = avg_RFQ_Xnormal[0]
# 모듈별 정상신호들 중에서 첫번째 인덱스의 14가지 유니크신호들을 plot함
for i in range(len(features)):
    plt.figure(figsize=(12, 6))
    plt.plot(avg_RFQ_Xnormal_plot[:, i], label="RFQ_Average")
    plt.legend()
    plt.xlabel("Time (s)")
    plt.ylabel(features[i])
    plt.title("Original vs Reconstructed")

    # 특수문자들 저장할때 오류나서 제대로 되지 않기에, 다음 값들로 변환함.
    # */ >> _
    if features[i] == 'A+*IGBT-I':
        features[i] = 'A+_IGBT-I'
    if features[i] == 'B+*IGBT-I':
        features[i] = 'B+_IGBT-I'
    if features[i] == 'C+*IGBT-I':
        features[i] = 'C+_IGBT-I'
    if features[i] == 'DV/DT':
        features[i] = 'DV_DT'
    
    plt.savefig('./figure/wave_scale/RFQ_AVG/' + str(features[i]) + '.png', dpi=600)

exit()
#################################### 정규화 ####################################
for i in range(len(features)):
    if i<=5 :
        Xnormal_concat[:,:,i] = standard.fit_transform(np.array(Xnormal_concat[:,:,i]).reshape(-1,1)).reshape(np.array(Xnormal_concat[:,:,i]).shape)
    if i>=6 and i<=8 :
        Xnormal_concat[:,:,i] = standard.fit_transform(Xnormal_concat[:,:,i].reshape(-1,1)).reshape(Xnormal_concat[:,:,i].shape)
    if i>=9 and i<=10 :
        Xnormal_concat[:,:,i] = standard.fit_transform(Xnormal_concat[:,:,i].reshape(-1,1)).reshape(Xnormal_concat[:,:,i].shape)
    if i>=11 :
        Xnormal_concat[:,:,i] = standard.fit_transform(Xnormal_concat[:,:,i].reshape(-1,1)).reshape(Xnormal_concat[:,:,i].shape)

print(f'the shape of standardized signal : {Xnormal_concat[524*0:524*0+1, :, 6]}') # 정규화된 신호 확인

for i in range(len(features)):
    if i>=0 and i<=5:
        Xnormal_concat[:,:,i] = scaler_IGBT.fit_transform(Xnormal_concat[:,:,i].reshape(-1, 1)).reshape(Xnormal_concat[:,:,i].shape)
    if i>=6 and i<=8:
        Xnormal_concat[:,:,i] = scaler_FLUX.fit_transform(Xnormal_concat[:,:,i].reshape(-1, 1)).reshape(Xnormal_concat[:,:,i].shape)
    if i>=9 and i<=10:
        Xnormal_concat[:,:,i] = scaler_CAP.fit_transform(Xnormal_concat[:,:,i].reshape(-1, 1)).reshape(Xnormal_concat[:,:,i].shape)
    if i>=11:
        Xnormal_concat[:,:,i] = scaler_MOD.fit_transform((Xnormal_concat[:,:,i]).reshape(-1, 1)).reshape((Xnormal_concat[:,:,i]).shape)

print(f'the shape of standardized & min-max signal : {Xnormal_concat[524*0:524*0+1, :, 6]}') # 정규화되고 나서 Min-Max 스케일링된 신호 확인

for i in range(len(features)):
    if i>=0 and i<=5:
        Xnormal_concat_tmp[:,:,i] = scaler_IGBT.fit_transform(Xnormal_concat_tmp[:,:,i].reshape(-1, 1)).reshape(Xnormal_concat_tmp[:,:,i].shape)
    if i>=6 and i<=8:
        Xnormal_concat_tmp[:,:,i] = scaler_FLUX.fit_transform(Xnormal_concat_tmp[:,:,i].reshape(-1, 1)).reshape(Xnormal_concat_tmp[:,:,i].shape)
    if i>=9 and i<=10:
        Xnormal_concat_tmp[:,:,i] = scaler_CAP.fit_transform(Xnormal_concat_tmp[:,:,i].reshape(-1, 1)).reshape(Xnormal_concat_tmp[:,:,i].shape)
    if i>=11:
        Xnormal_concat_tmp[:,:,i] = scaler_MOD.fit_transform((Xnormal_concat_tmp[:,:,i]).reshape(-1, 1)).reshape((Xnormal_concat_tmp[:,:,i]).shape)

print(f'the shape of min-max signal : {Xnormal_concat_tmp[524*0:524*0+1, :, 6]}') # Min-Max 스케일링된 신호 확인

for i in range(len(features)):
    if i>=0 and i<=5:
        Xnormal_concat_tmp[:,:,i] = standard_IGBT.fit_transform(Xnormal_concat_tmp[:,:,i].reshape(-1, 1)).reshape(Xnormal_concat_tmp[:,:,i].shape)
    if i>=6 and i<=8:
        Xnormal_concat_tmp[:,:,i] = standard_FLUX.fit_transform(Xnormal_concat_tmp[:,:,i].reshape(-1, 1)).reshape(Xnormal_concat_tmp[:,:,i].shape)
    if i>=9 and i<=10:
        Xnormal_concat_tmp[:,:,i] = standard_CAP.fit_transform(Xnormal_concat_tmp[:,:,i].reshape(-1, 1)).reshape(Xnormal_concat_tmp[:,:,i].shape)
    if i>=11:
        Xnormal_concat_tmp[:,:,i] = standard_MOD.fit_transform((Xnormal_concat_tmp[:,:,i]).reshape(-1, 1)).reshape((Xnormal_concat_tmp[:,:,i]).shape)

print(f'the shape of min-max & standardized signal : {Xnormal_concat_tmp[524*0:524*0+1, :, 6]}') # Min-Max 스케일링되고 나서 정규화된 신호 확인


#################################### 각 모듈별 정상신호들 중 첫번째 인덱스만 plot ####################################
x_RFQ = Xnormal_concat[524*0:524*0+1, :, :]
x_RFQ = x_RFQ[0]
x_RFQ = standard
x_DTL = Xnormal_concat[524*1:524*1+1, :, :]
x_DTL = x_DTL[0]
x_CCL = Xnormal_concat[524*2:524*2+1, :, :]
x_CCL = x_CCL[0]
x_SCL = Xnormal_concat[524*3:524*3+1, :, :]
x_SCL = x_SCL[0]

# 모듈 RFQ의 첫번째 정상신호의 shape 출력
print(x_RFQ.shape)

# 모듈별 정상신호들 중에서 첫번째 인덱스의 14가지 유니크신호들을 plot함
for i in range(len(features)):
    plt.figure(figsize=(12, 6))
    plt.plot(x_RFQ[:, i], label="RFQ")
    plt.plot(x_DTL[:, i], label="DTL")
    plt.plot(x_CCL[:, i], label="CCL")
    plt.plot(x_SCL[:, i], label="SCL")
    plt.legend()
    plt.xlabel("Time (s)")
    plt.ylabel(features[i])
    plt.title("Original vs Reconstructed")

    # 특수문자들 저장할때 오류나서 제대로 되지 않기에, 다음 값들로 변환함.
    # */ >> _
    if features[i] == 'A+*IGBT-I':
        features[i] = 'A+_IGBT-I'
    if features[i] == 'B+*IGBT-I':
        features[i] = 'B+_IGBT-I'
    if features[i] == 'C+*IGBT-I':
        features[i] = 'C+_IGBT-I'
    if features[i] == 'DV/DT':
        features[i] = 'DV_DT'
    
    plt.savefig('./figure/wave_scale/A-FLUX/' + str(features[i]) + '.png', dpi=600)

#################################### 각 모듈별 정상신호들 전부를 plot ####################################
# 524개의 샘플별로 오리지널 데이터를 표시함.
for i in range(len(features)):
    plt.figure(figsize=(12, 6))
    for k in range(524*3, 524*3+524):
        plt.plot(Xnormal_concat[k, :, i])
    plt.xlabel("Time (s)")
    plt.ylabel(features[i])
    plt.title("Original vs Reconstructed")

    # 특수문자들 저장할때 오류나서 제대로 되지 않기에, 다음 값들로 변환함.
    # */ >> _
    if features[i] == 'A+*IGBT-I':
        features[i] = 'A+_IGBT-I'
    if features[i] == 'B+*IGBT-I':
        features[i] = 'B+_IGBT-I'
    if features[i] == 'C+*IGBT-I':
        features[i] = 'C+_IGBT-I'
    if features[i] == 'DV/DT':
        features[i] = 'DV_DT'
    plt.savefig('./figure/wave_scale/RFQ/test/' + str(features[i]) + '.png', dpi=600)
        
plt.savefig('./figure/wave_scale/SCL/test_standard/' + str(features[i]) + '.png', dpi=600)

plt.clf() # figure 초기화
plt.cla() # figure 축 초기화
plt.close() # 현재 figure 닫기

exit()
for i in range(len(features)):
    if i<=5 :
        Xnormal_concat[:,:,i] = scaler_IGBT.fit_transform(np.array(Xnormal_concat[:,:,i]).reshape(-1,1)).reshape(np.array(Xnormal_concat[:,:,i]).shape)
    if i>=6 and i<=8 :
        Xnormal_concat[:,:,i] = scaler_FLUX.fit_transform(Xnormal_concat[:,:,i].reshape(-1,1)).reshape(Xnormal_concat[:,:,i].shape)
    if i>=9 and i<=10 :
        Xnormal_concat[:,:,i] = scaler_CAP.fit_transform(Xnormal_concat[:,:,i].reshape(-1,1)).reshape(Xnormal_concat[:,:,i].shape)
    if i>=11 :
        Xnormal_concat[:,:,i] = scaler_MOD.fit_transform(Xnormal_concat[:,:,i].reshape(-1,1)).reshape(Xnormal_concat[:,:,i].shape)
print(f'the shape of Xnormal_concat : {Xnormal_concat.shape}')

# 데이터 생성 : A-Flux Low Fault만을 수집
a_FLUX_FAULT_INDICES = np.where(Yanomaly_RFQ[:, 2] == 'A FLUX Low Fault')[0]

# 총 6개의 A-Flux Fault 중에서 마지막 인덱스 데이터를 테스트 셋으로 사용함.
data_test = Xnormal_RFQ[525:526,:,:]
# data_test = Xanomaly_RFQ[a_FLUX_FAULT_INDICES[0:1],:,:]
data_test = np.array(data_test)
for i in range(len(features)):
    if i>=0 and i<=5:
        data_test[:,:,i] = scaler_IGBT.transform(data_test[:,:,i].reshape(-1, 1)).reshape(data_test[:,:,i].shape)
    if i>=6 and i<=8:
        data_test[:,:,i] = scaler_FLUX.transform(data_test[:,:,i].reshape(-1, 1)).reshape(data_test[:,:,i].shape)
    if i>=9 and i<=10:
        data_test[:,:,i] = scaler_CAP.transform(data_test[:,:,i].reshape(-1, 1)).reshape(data_test[:,:,i].shape)
    if i>=11:
        data_test[:,:,i] = scaler_MOD.transform((data_test[:524,:,i]).reshape(-1, 1)).reshape((data_test[:524,:,i]).shape)

data_test = data_test.transpose(0,2,1)
print(f'the shape of data_test : {data_test.shape}')
data_test = torch.tensor(data_test, dtype=torch.float32)
labels_one_hot = torch.tensor(labels_one_hot, dtype=torch.float32)

# GPU 장치 설정
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# 모델 및 학습 설정
input_dim = 14
hidden_dim = 4500
latent_dim = 512
condition_dim = 4

model = CVAE(input_dim, hidden_dim, latent_dim, condition_dim).to(device)
optimizer = optim.Adam(model.parameters(), lr=1e-5)

# 학습한 모델 불러오기
# model.load_state_dict(torch.load('./model_june_week2/mutli-module_based_cvae_best1.pth'))
model.load_state_dict(torch.load('./model/mutli-module_based_cvae_best_ver_uniquewave_scaler.pth'))

# 예측 및 결과 시각화
model.eval()
with torch.no_grad():
    # print(data_test[0].unsqueeze(0))
    sample = data_test[0].unsqueeze(0).to(device)
    condition = labels_one_hot[524*1:524*1+1].unsqueeze(0).to(device)
    reconstructed, _, _ = model(sample, condition)
    # print(reconstructed)

    print(f'the shape of sample : {sample.shape}')
    print(f'the shape of reconstructed : {reconstructed.shape}')

    print(f'the shape of sample.squeeze(0) : {sample.squeeze(0).shape}')
    print(f'the shape of reconstructed.squeeze(0) : {reconstructed.squeeze(0).shape}')       
    print(sample.transpose(1,0)[0])
    print(reconstructed.transpose(1,0)[0])
    # 원래 데이터 형태로 복원
    sample = sample.squeeze(0).cpu().numpy().transpose(1, 0)  
    reconstructed = reconstructed.squeeze(0).cpu().numpy().transpose(1, 0)  
    
    # # 역정규화 추가
    # for i in range(len(features)):
    #     if i>=0 and i<=5:
    #         sample[:,i] = scaler_IGBT.inverse_transform(sample[:,i].reshape(-1, 1)).squeeze()
    #         reconstructed[:,i] = scaler_IGBT.inverse_transform(reconstructed[:,i].reshape(-1, 1)).squeeze()
    #     if i>=6 and i<=8:
    #         sample[:,i] = scaler_FLUX.inverse_transform(sample[:,i].reshape(-1, 1)).squeeze()
    #         reconstructed[:,i] = scaler_FLUX.inverse_transform(reconstructed[:,i].reshape(-1, 1)).squeeze()
    #     if i>=9 and i<=10:
    #         sample[:,i] = scaler_CAP.inverse_transform(sample[:,i].reshape(-1, 1)).squeeze()
    #         reconstructed[:,i] = scaler_CAP.inverse_transform(reconstructed[:,i].reshape(-1, 1)).squeeze()
    #     if i>=11:
    #         sample[:,i] = scaler_MOD.inverse_transform(sample[:,i].reshape(-1, 1)).squeeze()
    #         reconstructed[:,i] = scaler_MOD.inverse_transform(reconstructed[:,i].reshape(-1, 1)).squeeze()

for i in range(len(features)):
    plt.figure(figsize=(12, 6))
    plt.plot(sample[:, i], label="Original")
    plt.plot(reconstructed[:, i], label="Reconstructed")
    plt.legend()
    plt.xlabel("Time (s)")
    plt.ylabel(features[i])
    plt.title("Original vs Reconstructed")

    # 특수문자들 저장할때 오류나서 제대로 되지 않기에, 다음 값들로 변환함.
    # */ >> _
    if features[i] == 'A+*IGBT-I':
        features[i] = 'A+_IGBT-I'
    if features[i] == 'B+*IGBT-I':
        features[i] = 'B+_IGBT-I'
    if features[i] == 'C+*IGBT-I':
        features[i] = 'C+_IGBT-I'
    if features[i] == 'DV/DT':
        features[i] = 'DV_DT'
    
    plt.savefig('./figure/wave_scale/RFQ/test/' + str(features[i]) + '.png', dpi=600)
