import tensorflow as tf
import numpy as np
from scipy.misc import imsave
from skimage.transform import resize
from copy import deepcopy
import os
import cv2
from glob import glob
import constants as c
from loss_functions import combined_loss,lp_loss,adv_loss,gdl_loss,tv_loss
from utils import psnr_com
from tfutils import w, b

# noinspection PyShadowingNames    #####193line,optimizer.minimize   123line,convolution
class GeneratorModel:
    def __init__(self, session, summary_writer, height_train, width_train, height_test,
                 width_test, scale_layer_fms, scale_kernel_sizes):
        """
        Initializes a GeneratorModel.

        @param session: The TensorFlow Session.
        @param summary_writer: The writer object to record TensorBoard summaries
        @param height_train: The height of the input images for training.
        @param width_train: The width of the input images for training.
        @param height_test: The height of the input images for testing.
        @param width_test: The width of the input images for testing.
        @param scale_layer_fms: The number of feature maps in each layer of each scale network.
        @param scale_kernel_sizes: The size of the kernel for each layer of each scale network.

        @type session: tf.Session
        @type summary_writer: tf.train.SummaryWriter
        @type height_train: int
        @type width_train: int
        @type height_test: int
        @type width_test: int
        @type scale_layer_fms: list<list<int>>
        @type scale_kernel_sizes: list<list<int>>
        """
        self.sess = session
        self.summary_writer = summary_writer
        self.height_train = height_train
        self.width_train = width_train
        self.height_test = height_test
        self.width_test = width_test
        self.scale_layer_fms = scale_layer_fms
        self.scale_kernel_sizes = scale_kernel_sizes
        self.num_scale_nets = len(scale_layer_fms)

        self.define_graph()

    # noinspection PyAttributeOutsideInit
    def define_graph(self):
        """
        Sets up the model graph in TensorFlow.
        """
        with tf.name_scope('generator'):
            ##
            # Data
            ##

            with tf.name_scope('data'):
                self.input_frames_train = tf.placeholder(
                    tf.float32, shape=[None, self.height_train, self.width_train, 3 * c.HIST_LEN])
                self.gt_frames_train = tf.placeholder(
                    tf.float32, shape=[None, self.height_train, self.width_train, 3])

                self.input_frames_test = tf.placeholder(
                    tf.float32, shape=[None, self.height_test, self.width_test, 3 * c.HIST_LEN])
                self.gt_frames_test = tf.placeholder(
                    tf.float32, shape=[None, self.height_test, self.width_test, 3])

                # use variable batch_size for more flexibility
                self.batch_size_train = tf.shape(self.input_frames_train)[0]
                self.batch_size_test = tf.shape(self.input_frames_test)[0]

            ##
            # Scale network setup and calculation
            ##

            self.summaries_train = []
            self.scale_preds_train = []  # the generated images at each scale
            self.scale_gts_train = []  # the ground truth images at each scale
            self.d_scale_preds = []  # the predictions from the discriminator model

            self.summaries_test = []
            self.scale_preds_test = []  # the generated images at each scale
            self.scale_gts_test = []  # the ground truth images at each scale
            self.scale_lastinputs_train = []

            for scale_num in xrange(self.num_scale_nets):
                with tf.name_scope('scale_' + str(scale_num)):
                    with tf.name_scope('setup'):
                        ws = []
                        bs = []

                        # create weights for kernels
                        for i in xrange(len(self.scale_kernel_sizes[scale_num])):
                            ws.append(w([self.scale_kernel_sizes[scale_num][i],
                                         self.scale_kernel_sizes[scale_num][i],
                                         self.scale_layer_fms[scale_num][i],
                                         self.scale_layer_fms[scale_num][i + 1]]))
                            bs.append(b([self.scale_layer_fms[scale_num][i + 1]]))

                    with tf.name_scope('calculation'):
                        def calculate(height, width, inputs, gts, last_gen_frames):
                            # scale inputs and gts
                            scale_factor = 1. / 2 ** ((self.num_scale_nets - 1) - scale_num)
                            scale_height = int(height * scale_factor)
                            scale_width = int(width * scale_factor)

                            inputs = tf.image.resize_images(inputs, [scale_height, scale_width])
                            scale_last_inputs = inputs[:,:,:,-3:]
                            scale_gts = tf.image.resize_images(gts, [scale_height, scale_width])

                            # for all scales but the first, add the frame generated by the last
                            # scale to the input
                            if scale_num > 0:
                                last_gen_frames = tf.image.resize_images(
                                    last_gen_frames, [scale_height, scale_width])
                                inputs = tf.concat([inputs, last_gen_frames],3)

                            # generated frame predictions
                            preds = inputs

                            # perform convolutions
                            with tf.name_scope('convolutions'):
                                for i in xrange(len(self.scale_kernel_sizes[scale_num])):
                                    # Convolve layer
                                    preds = tf.nn.conv2d(
                                        preds, ws[i], [1, 1, 1, 1], padding=c.PADDING_G)

                                    # Activate with ReLU (or Tanh for last layer)
                                    if i == len(self.scale_kernel_sizes[scale_num]) - 1:
                                        preds = tf.nn.tanh(preds + bs[i])
                                    else:
                                        preds = tf.nn.relu(preds + bs[i])

                            return preds, scale_gts, scale_last_inputs

                        ##
                        # Perform train calculation
                        ##

                        # for all scales but the first, add the frame generated by the last
                        # scale to the input
                        if scale_num > 0:
                            last_scale_pred_train = self.scale_preds_train[scale_num - 1]
                        else:
                            last_scale_pred_train = None

                        # calculate
                        train_preds, train_gts, train_last_inputs = calculate(self.height_train,
                                                           self.width_train,
                                                           self.input_frames_train,
                                                           self.gt_frames_train,
                                                           last_scale_pred_train)
                        self.scale_preds_train.append(train_preds)
                        #self.buffer.append(train_preds)
                        self.scale_gts_train.append(train_gts)
                        self.scale_lastinputs_train.append(train_last_inputs)

                        # We need to run the network first to get generated frames, run the
                        # discriminator on those frames to get d_scale_preds, then run this
                        # again for the loss optimization.
                        if c.ADVERSARIAL:
                            self.d_scale_preds.append(tf.placeholder(tf.float32, [None, 1]))

                        ##
                        # Perform test calculation
                        ##

                        # for all scales but the first, add the frame generated by the last
                        # scale to the input
                        if scale_num > 0:
                            last_scale_pred_test = self.scale_preds_test[scale_num - 1]
                        else:
                            last_scale_pred_test = None

                        # calculate
                        test_preds, test_gts, test_last_inputs = calculate(self.height_test,
                                                         self.width_test,
                                                         self.input_frames_test,
                                                         self.gt_frames_test,
                                                         last_scale_pred_test)
                        self.scale_preds_test.append(test_preds)
                        self.scale_gts_test.append(test_gts)

            ##
            # Training
            ##

            with tf.name_scope('train'):
                # global loss is the combined loss from every scale network
                self.global_loss = combined_loss(self.scale_preds_train,
                                                 self.scale_gts_train,
                                                 self.d_scale_preds,
                                                 self.scale_lastinputs_train,
                                                 c.L_NUM,c.ALPHA_NUM,c.LAM_ADV,
                                                 c.LAM_LP,c.LAM_GDL,c.LAM_TV)
                self.l1_loss = c.LAM_LP*lp_loss(self.scale_preds_train,self.scale_gts_train, 1)
                batch_size = tf.shape(self.scale_preds_train[0])[0]
                self.adv_loss = c.LAM_ADV*adv_loss(self.d_scale_preds,tf.ones([4*batch_size, 1]))
                self.gdl_loss = c.LAM_GDL*gdl_loss(self.scale_preds_train,self.scale_gts_train, 1)
                self.tv_loss = c.LAM_TV*tv_loss(self.scale_preds_train)
               
                self.global_step = tf.Variable(0, trainable=False)
                self.optimizer = tf.train.AdamOptimizer(learning_rate=c.LRATE_G, name='optimizer')
                self.train_op = self.optimizer.minimize(self.global_loss,
                                                        global_step=self.global_step,
                                                        name='train_op')

                # train loss summary
                loss_summary = tf.summary.scalar('train_loss_G', self.global_loss)
                self.summaries_train.append(loss_summary)

            ##
            # Error
            ##

    def train_step(self, batch, discriminator=None):
        """
        Runs a training step using the global loss on each of the scale networks.

        @param batch: An array of shape
                      [c.BATCH_SIZE x self.height x self.width x (3 * (c.HIST_LEN + 1))].
                      The input and output frames, concatenated along the channel axis (index 3).
        @param discriminator: The discriminator model. Default = None, if not adversarial.

        @return: The global step.
        """
        ##
        # Split into inputs and outputs
        ##

        input_frames = batch[:, :, :, :-3]
        gt_frames = batch[:, :, :, -3:]


        ##
        # Train
        ##

        feed_dict = {self.input_frames_train: input_frames, self.gt_frames_train: gt_frames}

        if c.ADVERSARIAL:
            # Run the generator first to get generated frames
          
            scale_preds = self.sess.run(self.scale_preds_train, feed_dict=feed_dict)

            # Run the discriminator nets on those frames to get predictions
            d_feed_dict = {}
            
            for scale_num, gen_frames in enumerate(scale_preds):
                #####d_feed_dict[discriminator.scale_nets[scale_num].input_frames] = gen_frames
		b,h,w,s = np.shape(gen_frames)  
                local_gen_frames = np.empty([4*c.BATCH_SIZE, h/2,w/2,3]) 
                if gen_frames.shape[1]%2 != 0:
                   gen_frames = gen_frames[:,:-1,:,:]
                if gen_frames.shape[2]%2 != 0:
                   gen_frames = gen_frames[:,:,:-1,:]
                for i in range(c.BATCH_SIZE):
		    local_gen_frames[4*i]   = gen_frames[i,:h/2,:w/2,:]
		    local_gen_frames[4*i+1] = gen_frames[i,:h/2,w/2:,:]
		    local_gen_frames[4*i+2] = gen_frames[i,h/2:,:w/2,:]
		    local_gen_frames[4*i+3] = gen_frames[i,h/2:,w/2:,:] 
		d_feed_dict[discriminator.scale_nets[scale_num].input_frames] = local_gen_frames
            d_scale_preds = self.sess.run(discriminator.scale_preds, feed_dict=d_feed_dict)
          

            # Add discriminator predictions to the
            for i, preds in enumerate(d_scale_preds):
                feed_dict[self.d_scale_preds[i]] = preds
            #for i, preds in enumerate(d_buff_scale_preds):
                #feed_dict[self.d_buff_scale_preds[i]] = preds





        _, global_loss, l1_loss,adv_loss,gdl_loss,tv_loss, global_step, summaries = \
            self.sess.run([self.train_op,
                           self.global_loss,
                           self.l1_loss,
                           self.adv_loss,
                           self.gdl_loss,
                           self.tv_loss,
                           self.global_step,
                           self.summaries_train],
                           feed_dict=feed_dict)

        #gt_frames_history = batch[:, :, :, -3:]
        ##
        # User output
        ##
        if global_step % c.STATS_FREQ == 0:
            print 'GeneratorModel : Step ', global_step
            print '                 Global Loss    : ', global_loss
            print '                 l1_loss        : ', l1_loss
            print '                 adv_loss        : ', adv_loss
            print '                 gdl_loss        : ', gdl_loss
            print '                 tv_loss        : ', tv_loss
        if global_step % c.SUMMARY_FREQ == 0:
            self.summary_writer.add_summary(summaries, global_step)
            print 'GeneratorModel: saved summaries'
        if global_step % c.IMG_SAVE_FREQ == 0:
            print '-' * 30
            print 'Saving images...'

            # if not adversarial, we didn't get the preds for each scale net before for the
            # discriminator prediction, so do it now
            if not c.ADVERSARIAL:
                scale_preds = self.sess.run(self.scale_preds_train, feed_dict=feed_dict)

            # re-generate scale gt_frames to avoid having to run through TensorFlow.
            scale_gts = []
            for scale_num in xrange(self.num_scale_nets):
                scale_factor = 1. / 2 ** ((self.num_scale_nets - 1) - scale_num)
                scale_height = int(self.height_train * scale_factor)
                scale_width = int(self.width_train * scale_factor)

                # resize gt_output_frames for scale and append to scale_gts_train
                scaled_gt_frames = np.empty([c.BATCH_SIZE, scale_height, scale_width, 3])
                for i, img in enumerate(gt_frames):
                    # for skimage.transform.resize, images need to be in range [0, 1], so normalize
                    # to [0, 1] before resize and back to [-1, 1] after
                    img=np.clip(img,-1.0,1.0)
                    sknorm_img = (img / 2) + 0.5
                    resized_frame = resize(sknorm_img, [scale_height, scale_width, 3])
                    scaled_gt_frames[i] = (resized_frame - 0.5) * 2
                scale_gts.append(scaled_gt_frames)

            # for every clip in the batch, save the inputs, scale preds and scale gts
            for pred_num in xrange(len(input_frames)):
                pred_dir = c.get_dir(os.path.join(c.IMG_SAVE_DIR, 'Step_' + str(global_step),
                                                  str(pred_num)))

                # save input images
                for frame_num in xrange(c.HIST_LEN):
                    img = input_frames[pred_num, :, :, (frame_num * 3):((frame_num + 1) * 3)]
                    imsave(os.path.join(pred_dir, 'input_' + str(frame_num) + '.png'), img)

                # save preds and gts at each scale
                # noinspection PyUnboundLocalVariable
                for scale_num, scale_pred in enumerate(scale_preds):
                    gen_img = scale_pred[pred_num]

                    path = os.path.join(pred_dir, 'scale' + str(scale_num))
                    gt_img = scale_gts[scale_num][pred_num]

                    imsave(path + '_gen.png', gen_img)
                    imsave(path + '_gt.png', gt_img)

            print 'Saved images!'
            print '-' * 30

        return global_step

    def test_batch(self, batch, global_step, num_rec_out=1, save_imgs=True):
        """
        Runs a training step using the global loss on each of the scale networks.

        @param batch: An array of shape
                      [batch_size x self.height x self.width x (3 * (c.HIST_LEN+ num_rec_out))].
                      A batch of the input and output frames, concatenated along the channel axis
                      (index 3).
        @param global_step: The global step.
        @param num_rec_out: The number of outputs to predict. Outputs > 1 are computed recursively,
                            using previously-generated frames as input. Default = 1.
        @param save_imgs: Whether or not to save the input/output images to file. Default = True.

        @return: A tuple of (psnr error, sharpdiff error) for the batch.
        """
        if num_rec_out < 1:
            raise ValueError('num_rec_out must be >= 1')

        print '-' * 30
        print 'Testing:'

        ##
        # Split into inputs and outputs
        ##

        input_frames = batch[:, :, :, :3 * c.HIST_LEN]
        gt_frames = batch[:, :, :, 3 * c.HIST_LEN:]

        ##
        # Generate num_rec_out recursive predictions
        ##

        working_input_frames = deepcopy(input_frames)  # input frames that will shift w/ recursion
        rec_preds = []
        rec_summaries = []
        for rec_num in xrange(num_rec_out):
            working_gt_frames = gt_frames[:, :, :, 3 * rec_num:3 * (rec_num + 1)]

            feed_dict = {self.input_frames_test: working_input_frames,
                         self.gt_frames_test: working_gt_frames}
            preds,summaries = self.sess.run([self.scale_preds_test[-1],
                                   
                                                              self.summaries_test],
                                                              feed_dict=feed_dict)

            # remove first input and add new pred as last input
            working_input_frames = np.concatenate(
                [working_input_frames[:, :, :, 3:], preds], axis=3)

            # add predictions and summaries
            rec_preds.append(preds)
            rec_summaries.append(summaries)

        # write summaries
        # TODO: Think of a good way to write rec output summaries - rn, just using first output.

        ##
        # Save images
        ##

        if save_imgs:
            for pred_num in xrange(len(input_frames)):
                pred_dir = c.get_dir(os.path.join(
                    c.IMG_SAVE_DIR, 'Tests/Step_' + str(global_step), str(pred_num)))

                # save input images
                for frame_num in xrange(c.HIST_LEN):
                    img = input_frames[pred_num, :, :, (frame_num * 3):((frame_num + 1) * 3)]
                    imsave(os.path.join(pred_dir, 'input_' + str(frame_num) + '.png'), img)

                # save recursive outputs
                for rec_num in xrange(num_rec_out):
                    gen_img = rec_preds[rec_num][pred_num]
                    gt_img = gt_frames[pred_num, :, :, 3 * rec_num:3 * (rec_num + 1)]
                    imsave(os.path.join(pred_dir, 'gen_' + str(rec_num) + '.png'), gen_img)
                    imsave(os.path.join(pred_dir, 'gt_' + str(rec_num) + '.png'), gt_img)
                gen_path = sorted(glob(os.path.join(pred_dir, 'gen_*.png')))
                gt_path = sorted(glob(os.path.join(pred_dir, 'gt_*.png')))
                for i in range(num_rec_out):
                    gen = cv2.imread(gen_path[i])
                    gt = cv2.imread(gt_path[i])
                    p = psnr_com(gen, gt)
                    print 'Recursion ', i , 'PSNR' , p

        print '-' * 30



