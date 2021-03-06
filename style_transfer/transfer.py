import copy
import matplotlib.pyplot as plt
import numpy as np
import os
import skimage.io
import tensorflow as tf
import pdb

from ext.tf_vgg import vgg19, utils
from optimize import SGD

PAUSE_LEN = 0.01    # length to pause when displaying plots
NUM_CHANNELS = 3    # number of color channels


class Transfer:

  def __init__(self, style, content, width = 240, height = 240, initial = None, 
               content_layers = ["conv4_2"], 
               style_layers = ["conv1_1","conv2_1",
                               "conv3_1","conv4_1",
                               "conv5_1"]):
    self.content_layers = content_layers
    self.style_layers = style_layers

    # Desired size of output image
    self.width = width
    self.height = height

    self.sess = tf.Session()

    # Create the 'VGG19' convolutional neural net
    self.image = tf.placeholder('float', [1, self.width, self.height, NUM_CHANNELS])
    self.vgg = vgg19.Vgg19()
    self.vgg.build(self.image)

    # Read in style and content images and then resize
    style = utils.load_image2(style, self.width, self.height)
    content = utils.load_image2(content, self.width, self.height)

    # Convert content and style to BGR
    new_image_shape = (1, self.width, self.height, NUM_CHANNELS)
    self.style = self.vgg.toBGR(style.reshape(new_image_shape))
    self.content = self.vgg.toBGR(content.reshape(new_image_shape))

    # Get the feature maps for the style and content we want
    self.target_content = self.get_content_features(self.content)
   
    # Create symbolic gram matrices and target gram matrices for style image
    self.gram_matrix_functions = self.get_gram_matrices()
    self.target_gram_matrices = [] 
    for G in self.gram_matrix_functions:
      self.target_gram_matrices.append(self.sess.run(G, {self.image : self.style}))

    self.synthetic = self.image

  

  #############################################################################
  # content representation
  #############################################################################

  def get_content_features(self, image):
    if image.shape != (1, self.width, self.width, NUM_CHANNELS):
      image = tf.reshape(image, (1, self.width, self.width, NUM_CHANNELS))
      image = self.sess.run(image, {self.image : self.synthetic})
    content = {}
    for layer in self.content_layers:
      content[layer] = self.sess.run(self.vgg[layer], feed_dict={self.image : image})[0]
    return content 

  def get_content_loss(self, image):
    if image.shape != (1, self.width, self.width, NUM_CHANNELS):
      image = tf.reshape(image, (1, self.width, self.width, NUM_CHANNELS))
      image = self.sess.run(image, {self.image : self.synthetic})
    loss = self.get_content_loss_function()
    return self.sess.run(loss, {self.image : image})

  def get_content_loss_function(self):
    content_layer_loss = []
    for layer in self.content_layers:
      F_minus_P = self.vgg[layer] - tf.constant(self.target_content[layer])
      F_minus_P_2 = 0.5 * tf.square(F_minus_P)
      content_layer_loss.append(tf.reduce_mean(F_minus_P_2))
    return tf.reduce_mean(content_layer_loss)

  def get_content_loss_gradient(self, image):
    if image.shape != (1, self.width, self.width, NUM_CHANNELS):
      image = tf.reshape(image, (1, self.width, self.width, NUM_CHANNELS))
      image = self.sess.run(image, {self.image : self.synthetic})
    loss = self.get_content_loss_function()
    gr = tf.gradients(loss, self.image)
    content_gradient = self.sess.run(gr, {self.image : image})[0]
    content_loss = self.sess.run(loss, {self.image : image})
    return (content_gradient, content_loss)


  #############################################################################
  # style representation
  #############################################################################

  def get_style_features(self):
    style = []
    for layer in self.style_layers:
      style.append(self.vgg[layer])
    return style


  def get_gram_matrices(self):
    features = self.get_style_features()
    gram_matrices = []
    for l in range(len(self.style_layers)):
      num_feature = self.sess.run(tf.shape(features[l])[3])

      # Using '-1' flattens the tensor. So -1 = 'M_L**2' in this case.
      A = tf.reshape(features[l], [-1, num_feature])
      gram_matrices.append(tf.matmul(A, A, transpose_a = True))
    return gram_matrices


  def get_style_loss(self, image):
    if image.shape != (1, self.width, self.height, NUM_CHANNELS):
      image = tf.reshape(image, (1, self.width, self.height, NUM_CHANNELS))
      image = self.sess.run(image, {self.image : self.synthetic})
    loss_style = self.get_style_loss_function()
    return self.sess.run(loss_style, {self.image : image})

  def get_style_loss_function(self):
    E = []
    for l in range(len(self.target_gram_matrices)):
      E.append(tf.reduce_mean(tf.square(self.gram_matrix_functions[l] - self.target_gram_matrices[l])))
    return tf.reduce_mean(E)


  def get_style_loss_gradient(self, image):
    if image.shape != (1, self.width, self.height, NUM_CHANNELS):
      image = tf.reshape(image, (1, self.width, self.height, NUM_CHANNELS))
      image = self.sess.run(image, {self.image : self.synthetic})
    loss = self.get_style_loss_function()
    gr = tf.gradients(loss, self.image)
    style_gradient = self.sess.run(gr, {self.image : image})[0]
    style_loss = self.sess.run(loss, {self.image : image})
    return (style_gradient, style_loss)



  #############################################################################
  # execute
  #############################################################################

  def transfer_style_to_image(self, out_dir = '.', alpha = 1, beta = 1,
                              params = {
                                'type' : 'sgd',
                                'step_size' : 1.0,
                                'iters' : 100,
                                'gamma' : 0.9
                              }):
    synthetic = copy.copy(self.synthetic)
    def loss_gradient(image):
      c_grad, c_loss = self.get_content_loss_gradient(image)
      s_grad, s_loss = self.get_style_loss_gradient(image)
      print('-------------------------')
      print('Style Loss = {}'.format(beta*s_loss))
      print('Content Loss = {}'.format(alpha*c_loss))
      print('Content / Style loss {}'.format((alpha*c_loss) / (beta*s_loss)))
      return (alpha*c_grad + beta*s_grad, alpha*c_loss + beta*s_loss)

    def loss(image):
      c_loss = self.get_content_loss(image)
      s_loss = self.get_style_loss(image)
      
      return alpha*c_loss + beta*s_loss
    
    base_params = {
      'name' : 'Image Style Transfer',
      'theta' : synthetic,
      'dJdTheta' : loss_gradient,
      'J' : loss,
      'init_display' : self._init_display,
      'update_display' : self._update_display,
      'save' : self._save,
      'out_dir' : out_dir
    }
    base_params.update(params)
     
    return SGD(base_params).optimize()


  # note that with the SciPy L-BFGS implementation, the image must be
  # recorded as a vector
  def transfer_style_to_image_lbfgs(self, out_dir = '.', alpha = 1, beta = 1,
                              params = {
                                'type' : 'sgd',
                                'step_size' : 1.0,
                                'iters' : 100,
                                'gamma' : 0.9
                              }):
    synthetic = copy.copy(self.synthetic)

    params['loss'] = []
    params['iter'] = 0          # track number of iterations
    params['name'] = 'L-BFGS Image Style Transfer'

    def loss_gradient(image):
      c_grad, c_loss = self.get_content_loss_gradient(image)
      s_grad, s_loss = self.get_style_loss_gradient(image)
      print('Style loss = {}'.format(s_loss))
      print('Content loss = {}'.format(c_loss))
      print('Content / Style loss {}'.format(c_loss / s_loss))
      out = alpha * c_grad + beta * s_grad
      out = out.flatten()
      return np.float64(out)     # convert to float64

    def loss(image):
      # update display
      result = tf.reshape(image, (1, self.width, self.height, NUM_CHANNELS))
      result = self.sess.run(result, {self.image : self.synthetic})
      result = self.vgg.toRGB(result)[0]
      result = np.clip(result, 0, 1)
      im.set_data(result)
      skimage.io.imsave(os.path.join(out_dir, 'lbfgs_style_transfer.jpg'), result[0])
      plt.title('{} (iteration {})'.format(params['name'], params['iter']))
      plt.pause(PAUSE_LEN)

      # get loss and compute loss function
      c_loss = self.get_content_loss(image)
      s_loss = self.get_style_loss(image)

      loss = alpha*c_loss + beta*s_loss

      params['iter'] += 1
      params['loss'].append(loss)
      return loss

    plt.ion()
    plt.title('L-BFGS Image Style Transfer')
    im = plt.imshow(np.clip(self.vgg.toRGB(synthetic)[0], 0, 1))
    plt.pause(PAUSE_LEN)

    self.synthetic = synthetic
    theta = tf.reshape(synthetic, [-1])      # flatten vector
    theta = tf.cast(theta, tf.float64)       # convert to tf.float64. necessary for scipy.optimize
    theta = self.sess.run(theta, {self.image : synthetic})
    base_params = {
      'theta' : theta,
      'dJdTheta' : loss_gradient,
      'J' : loss,
      'init_display' : self._init_display,
      'update_display' : self._update_display,
      'save' : self._save,
      'out_dir' : out_dir
    }
    base_params.update(params)

    return SGD(base_params).optimize_lbfgs()
  

  def transfer_only_content(self, out_dir = '.', params = {
                              'type' : 'sgd',
                              'step_size' : 1.0,
                              'iters' : 100,
                              'gamma' : 0.9   # Used as part of momentum
                            }):
    synthetic = copy.copy(self.synthetic)
    base_params = {
      'name' : 'Content Transfer',
      'theta' : synthetic,
      'dJdTheta' : self.get_content_loss_gradient,
      'J' : self.get_content_loss,
      'init_display' : self._init_display,
      'update_display' : self._update_display,
      'save' : self._save,
      'out_dir' : out_dir
    }
    base_params.update(params)

    return SGD(base_params).optimize()

  def transfer_only_style(self, out_dir = '.', params = {
                            'type' : 'sgd',
                            'step_size' : 1.0,
                            'iters' : 100,
                            'gamma' : 0.9   # Used as part of momentum.
                          }):
    synthetic = copy.copy(self.synthetic)
    base_params = {
      'name' : 'Style Transfer',
      'theta' : synthetic,
      'dJdTheta' : self.get_style_loss_gradient,
      'J' : self.get_style_loss,
      'init_display' : self._init_display,
      'update_display' : self._update_display,
      'save' : self._save,
      'out_dir' : out_dir
    }
    base_params.update(params)
    return SGD(base_params).optimize()

  #############################################################################
  # utility
  #############################################################################

  def set_initial_img(self, image):
    image = utils.load_image2(image, self.width, self.height)
    image = image.reshape((1, self.width, self.height, NUM_CHANNELS))
    self.synthetic = self.vgg.toBGR(image)

  def set_random_initial_img(self):
      rand_noise = np.random.rand(self.width, self.height)
      rand_noise = rand_noise.reshape(1, self.width, self.height, 1)
      white_noise = np.concatenate((rand_noise, rand_noise, rand_noise), 
                                   axis=NUM_CHANNELS)
      self.synthetic = self.vgg.toBGR(white_noise)


  def open_image(self, image_path):
    image = utils.load_image2(image_path, self.width, self.height)
    return image.reshape((1, self.width, self.height, NUM_CHANNELS))


  # Shared 'lambda' functions used inside of optimize to display images
  # as they are being updated/generated
  def _init_display(self, params):
    plt.title(params['name'])
    plt.ion()
    params['im'] = plt.imshow(np.clip(self.vgg.toRGB(params['theta'])[0], 0, 1))


  def _update_display(self, params):
    params['im'].set_data(np.clip(self.vgg.toRGB(params['theta'])[0], 0, 1))
    plt.pause(PAUSE_LEN)
    print('-------')
    print('Loss on iteration {}: {}'.format(params['iter'], params['loss'][-1]))


  def _save(self, params):
    image = params['theta']
    if image.shape != (1, self.width, self.width, NUM_CHANNELS):
        image = tf.reshape(image, (1, self.width, self.width, NUM_CHANNELS))
        image = self.sess.run(image, {self.image : self.synthetic})

    out = self.vgg.toRGB(image)
    out = np.clip(out, 0, 1)

    filename = params['type'] + '_' + params['name'] 
    skimage.io.imsave(os.path.join(params['out_dir'], filename + '.jpg'), out[0])
    
    plt.clf()
    f, ax = plt.subplots(1)
    ax.set_ylim(bottom=0, top = max(params['loss']))

    plt.plot(params['loss'])
    plt.savefig(os.path.join(params['out_dir'], filename + '_loss.jpg'))

    return out 

