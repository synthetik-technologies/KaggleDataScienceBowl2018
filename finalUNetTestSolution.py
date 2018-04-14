#macro to create masks for final kaggle submission
#uses a U-Net to create pixel labels, then KMeans to cluster connected pixels with nuclei confidence > 0.5
#thanks to:
#-Kjetil Amdal-Saevik and his Kernel "Keras U-Net starter - LB 0.277"
#-the github repo unet-tensorflow-keras
import os
import sys
import random
import warnings

import numpy as np
import pandas as pd

import matplotlib.pyplot as plt

from tqdm import tqdm
from itertools import chain
from skimage.io import imread, imshow, imread_collection, concatenate_images
from skimage.transform import resize
from skimage.morphology import label
from skimage.color import rgb2gray
from sklearn.cluster import KMeans, DBSCAN

from keras.models import Model, load_model
from keras.layers import Input
from keras.layers.core import Dropout, Lambda
from keras.layers.convolutional import Conv2D, Conv2DTranspose
from keras.layers.pooling import MaxPooling2D
from keras.layers.merge import concatenate
from keras.callbacks import EarlyStopping, ModelCheckpoint
from keras import backend as K

import tensorflow as tf

from modelZoo import UNet


# Run-length encoding stolen from https://www.kaggle.com/rakhlin/fast-run-length-encoding-python
def rle_encoding(x):
        dots = np.where(x.T.flatten() == 1)[0]
        run_lengths = []
        prev = -2
        for b in dots:
                if (b>prev+1): run_lengths.extend((b + 1, 0))
                run_lengths[-1] += 1
                prev = b
        return run_lengths

#try kmeans with nClust clusters, if nClust>1 shows substantial inertia improvement, return it
def bestKM(maskAsArray):

        nClust=5
        runningPred=0
        runningInertia=0

        for i in range(1,nClust+1):
                #would like more initialisations but runtime limited
                kmFit=KMeans(n_clusters=i,init='k-means++',n_init=2)
                predClustKM=kmFit.fit_predict(maskAsArray)

                if i > 1 and kmFit.inertia_ > (0.49+(i>2)*0.15)*runningInertia:
                        return runningPred
                else:
                        runningPred=predClustKM
                        runningInertia=kmFit.inertia_

        return runningPred

#recluster original masks using a clustering algorithm
def recluster(urMask):
        clusterList=[]
        print (urMask.max() + 1)
        for i in range(1, urMask.max() + 1):
                mask= urMask == i
                
                if np.count_nonzero(mask) < 5:
                        clusterList.append(mask)
                        continue

                maskAsList=[]
                for j in range(mask.shape[0]):
                        for k in range(mask.shape[1]):
                             if mask[j][k]>0:
                                     maskAsList.append([j,k])

                maskAsArray=np.stack(maskAsList)
                predClustKM=bestKM(maskAsArray)
                nKMClust=np.amax(predClustKM)

                if nKMClust==0:
                        clusterList.append(mask)
                else:
                        for j in range(nKMClust+1):
                                subMask=np.zeros((mask.shape[0],mask.shape[1]))

                                for k in range(len(predClustKM)):
                                        if predClustKM[k]==j:
                                                subMask[maskAsArray[k,0]][maskAsArray[k,1]]=1
                                        
                                clusterList.append(subMask)                
                                                
        return clusterList

def prob_to_rles(x, cutoff=0.5):
        print (x.shape)
        lab_img = label(x > cutoff)
        clusterList=recluster(lab_img)
        for i in range(len(clusterList)):
                yield rle_encoding(clusterList[i].astype(np.bool))

# Set some parameters
IMG_WIDTH = 384
IMG_HEIGHT = 384
IMG_CHANNELS = 3
TEST_PATH = 'stage2_test_final/'

warnings.filterwarnings('ignore', category=UserWarning, module='skimage')
seed = 42
random.seed = seed
np.random.seed = seed

# Get train and test IDs
test_ids = next(os.walk(TEST_PATH))[1]

# Get and resize test images
#X_test = np.zeros((len(test_ids), IMG_HEIGHT, IMG_WIDTH, IMG_CHANNELS), dtype=np.uint8)
sizes_test = []
print('Getting and resizing test images ... ')
sys.stdout.flush()

# Predict on train, val and test
model = load_model('model-dsbowl2018-hqsizeshift.h5')
new_test_ids = []
rles = []

for n, id_ in tqdm(enumerate(test_ids), total=len(test_ids)):
        path = TEST_PATH + id_
        #print (path)
        rawImg = imread(path + '/images/' + id_ + '.png')
        if rawImg.ndim==2:
                placeHolder=np.zeros((rawImg.shape[0],rawImg.shape[1],3))
                placeHolder[:,:,0]=rawImg
                placeHolder[:,:,1]=rawImg
                placeHolder[:,:,2]=rawImg
                rawImg=placeHolder
                
        #print (rawimg.shape)
        img = rawImg[:,:,:IMG_CHANNELS]
        sizes_test.append([img.shape[0], img.shape[1]])
        img = resize(img, (IMG_HEIGHT, IMG_WIDTH), mode='constant', preserve_range=True)
        placeHolderImg=np.zeros((1,IMG_HEIGHT,IMG_WIDTH,3))
        placeHolderImg[0,:,:,:]=img
        img=placeHolderImg

        div = img.max(axis=tuple(np.arange(1,len(img.shape))), keepdims=True) 
        div[div < 0.01*img.mean()] = 1. # protect against too small pixel intensities
        img = img.astype(np.float32)/div
        
        preds_test = model.predict([img], verbose=0)
        
        # Create upsampled test mask
        preds_test_upsampled = resize(np.squeeze(preds_test),
                                           (sizes_test[n][0], sizes_test[n][1]),
                                           mode='constant', preserve_range=True)

        rle = list(prob_to_rles(preds_test_upsampled))
        #print (rle)
        if len(rle)==0:
                rle=[[1,1]]
        rles.extend(rle)
        new_test_ids.extend([id_] * len(rle))

        plt.imshow(preds_test_upsampled)
        plt.savefig(path + '/images/bestAnswerFull' + id_ + '.png',dpi=100)
        plt.clf()

        plt.imshow((preds_test_upsampled>0.5).astype(np.uint8))
        plt.savefig(path + '/images/bestAnswerMask' + id_ + '.png',dpi=100)
        plt.clf()

        
# Create submission DataFrame
sub = pd.DataFrame()
sub['ImageId'] = new_test_ids
sub['EncodedPixels'] = pd.Series(rles).apply(lambda x: ' '.join(str(y) for y in x))
sub.to_csv('sub-dsbowl2018-1.csv', index=False)
