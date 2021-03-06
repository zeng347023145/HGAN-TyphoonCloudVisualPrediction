Visual Prediction of Typhoon Clouds with Hierarchical Generative Adversarial Networks
============
This is a tensorflow implementation of visual prediction of typhoon clouds with hierarchical generative adversarial networks.


Requirements:
--------------

Python 2.7

Tensorflow 1.2.0


You can download the pretrained model here https://pan.baidu.com/s/1Eyanke10-h75vamsWK5MYQ. The password is vtmk.
The downloaded three files should be put in 'HGAN-TyphoonCloudVisualPrediction/Save/Models/'.

Test the model:
----------------

python avg_runner -n name -l (xx/xx)/HGAN-TyphoonCloudVisualPrediction/Save/Models/model.ckpt -T


Train a new model:
------------------

python avg_runner.py -n name -s steps


Training data:/Data/Train/xx/

Testing data:/Data/Test/xx/

The models trained and generated images will be saved in '/Save/..'

Results demos
----
*  Demo 1 ( Typhoon **Morakot** ) :

The following demo shows the **prediction** of continuous typhoon cloud movements in ten time steps of the typhoon Morakot.

![image]( https://github.com/lihuiupc/HGAN-TyphoonCloudVisualPrediction/blob/master/Demos/morakot_gen.gif)

The following dynamic map shows the optical flow for the **predicted** typhoon cloud sequence. The optical flow indicates the direction and size of typhoon cloud movements.

![image]( https://github.com/lihuiupc/HGAN-TyphoonCloudVisualPrediction/blob/master/Demos/morakot_gen_flow.gif)

*  Demo 2 ( Typhoon **Maria** ) :

The following demo shows the **prediction** of continuous typhoon cloud movements in ten time steps of the typhoon Maria.

![image]( https://github.com/lihuiupc/HGAN-TyphoonCloudVisualPrediction/blob/master/Demos/maria_gen.gif)

The following dynamic map shows the optical flow for the **predicted** typhoon cloud sequence. 

![image]( https://github.com/lihuiupc/HGAN-TyphoonCloudVisualPrediction/blob/master/Demos/maria_gen_flow.gif)

We acknowledge the authors for the code released at ''https://github.com/dyelax/Adversarial_Video_Generation'', which provides useful operations for our implementation.
