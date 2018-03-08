import copy
import matplotlib.pyplot as plt
import numpy as np
import os
import skimage.io
import tensorflow as tf
import pdb

from ext.tf_vgg import vgg19, utils


# length to pause when displaying plots
PAUSE_LEN = 0.01

class Transfer:

  def __init__(self, style, content, width = 240, height = 240, initial = None, 
               content_layers = ["conv4_2"], style_layers = ["conv1_1","conv2_1","conv3_1","conv4_1","conv5_1"]):
    self.content_layers = content_layers
    self.style_layers = style_layers

    # Desired size of output image
    self.width = width
    self.height = height

    self.sess = tf.Session()

    # Create the "VGG19" convolutional neural net
    self.image = tf.placeholder("float", [1, self.width, self.height, 3])
    self.vgg = vgg19.Vgg19()
    self.vgg.build(self.image)

    if not initial:
      rand_noise = np.random.rand(self.width, self.height)
      rand_noise = rand_noise.reshape(1, self.width, self.height,1)
      white_noise = np.concatenate((rand_noise, rand_noise, rand_noise), axis=3)
      self.synthetic = white_noise
    else:
      self.synthetic = initial

    # Read in style and content images and then resize
    style = utils.load_image2(style, self.width, self.height)
    content = utils.load_image2(content, self.width, self.height)

    # Get feature repesentation of content and style
    new_image_shape = (1, self.width, self.height, 3)
    self.style = self.vgg.toBGR(style.reshape(new_image_shape))
    self.content = self.vgg.toBGR(content.reshape(new_image_shape))
    self.synthetic = self.vgg.toBGR(self.synthetic.reshape(new_image_shape))

    # Get the feature maps for the style and content we want
    self.target_style = self.get_style_features(self.style)
    self.target_content = self.get_content_features(self.content)


  #############################################################################
  # content representation
  #############################################################################

  def get_content_features(self, image):
    content = {}
    for layer in self.content_layers:
      content[layer] = self.sess.run(self.vgg[layer], feed_dict={self.image : image})[0]
    return content 

  def get_content_loss(self, image):
    loss = self.get_content_loss_function()
    return self.sess.run(loss, {self.image : image })

  def get_content_loss_function(self):
    content_layer_loss = []
    for layer in self.content_layers:
      F_minus_P = self.vgg[layer] - tf.constant(self.target_content[layer])
      F_minus_P_2 = 0.5 * tf.square(F_minus_P)
      content_layer_loss.append(tf.reduce_mean(F_minus_P_2))
    return tf.reduce_mean(content_layer_loss)

  def get_content_loss_gradient(self, image):
    loss = self.get_content_loss_function()
    gr = tf.gradients(loss, self.image)
    content_gradient = self.sess.run(gr, {self.image : image})[0]
    content_loss = self.sess.run(loss, { self.image : image})
    return (content_gradient, content_loss)


  #############################################################################
  # style representation
  #############################################################################

  def get_style_features(self, image):
    style = []

    feed = {self.image : image}

    for layer in self.style_layers:
      style.append(self.vgg[layer])
    
    return style


  def get_gram_matrix(self, features):
    gram = []
    for l in range(len(self.style_layers)):
      num_feature = self.sess.run(tf.shape(features[l])[3])
      M_l = self.sess.run(tf.shape(features[l])[1])
      A = tf.reshape(features[l], [M_l ** 2, num_feature])
      gram.append(tf.matmul(A, A, transpose_a = True))

    return gram


  def get_style_loss(self, image, loss):
    # style representation
    # loss_style = sum(weighting_l * E_l)
    return self.sess.run(loss, {self.image : image})


  def get_style_loss_function(self, generated_image):
    A = self.get_gram_matrix(self.get_style_features(self.style))
    G = self.get_gram_matrix(self.get_style_features(generated_image))

    # test gram matrix
    G_run = self.sess.run(G[0], {self.image: generated_image})

    for l in range(len(A)):
      A[l] = self.sess.run(A[l], {self.image : self.style})

    print('--------')
    print('get_style_loss_function')
    E = []
    for l in range(len(self.style_layers)):
      N_l = A[l].shape[0]                   # number of features
      M_l = A[l].shape[0] * A[l].shape[1]   # feature map size (number of features: h x w)
      G_minus_A = G[l] - A[l]
      G_minus_A_2 = 1 / (4 * N_l^2 * M_l^2) * tf.square(G_minus_A)
      E.append(tf.reduce_sum(G_minus_A_2))
      E_run = self.sess.run(E[-1], {self.image : generated_image})

    # get weighted sum, which is average
    return tf.reduce_mean(E)


  def get_style_loss_gradient(self, generated_image):
    loss = self.get_style_loss_function(generated_image)
    print('-----')
    print('get_style_loss_gradient')
    gr = tf.gradients(loss, self.image)
    style_gradient = self.sess.run(gr, {self.image : generated_image})[0]
    style_loss = loss

    return (style_gradient, style_loss)



  #############################################################################
  # execute
  #############################################################################

  def transfer_only_content(self, step_size = 10.0, iters = 100, out_dir = "."):
    synthetic = copy.copy(self.synthetic)

    plt.title("Content Transfer")
    plt.ion()
    im = plt.imshow(np.clip(self.vgg.toRGB(synthetic)[0], 0, 1))

    loss = []
    for i in range(iters):

      syn_gradient, syn_loss = self.get_content_loss_gradient(synthetic)
      print('-------')
      synthetic -= step_size * syn_gradient
      loss.append(syn_loss)
      im.set_data(np.clip(self.vgg.toRGB(synthetic)[0], 0, 1))
      plt.pause(PAUSE_LEN)
      print("Loss on iteration {}: {}".format(i, loss[-1]))

    out = self.vgg.toRGB(synthetic)
    out = np.clip(out, 0, 1)
    skimage.io.imsave(os.path.join(out_dir, "content_only_transfer.jpg"), out[0])

    plt.plot(loss)
    plt.savefig(os.path.join(out_dir, "content_loss.jpg"))

    return out


  def transfer_only_style(self, step_size = 10.0, iters = 100, out_dir = "."):
    synthetic = copy.copy(self.synthetic)   # get white noise image

    plt.title("Style Transfer")
    plt.ion()                               # interactive mode on
    im = plt.imshow(np.clip(self.vgg.toRGB(synthetic)[0], 0, 1))

    loss = []
    for i in range(iters):
      (syn_gradient, style_loss) = self.get_style_loss_gradient(synthetic)
      print('syn_gradient is {}'.format(syn_gradient.shape))
      synthetic -= step_size * syn_gradient
      loss.append(self.get_style_loss(synthetic, style_loss))
      im.set_data(np.clip(self.vgg.toRGB(synthetic)[0], 0, 1))
      plt.pause(PAUSE_LEN)
      print("Loss on iteration {}: {}".format(i, loss[-1]))

    # out = self.vgg.toRGB(synthetic)
    # out = np.clip(out, 0, 1)
    # skimage.io.imsave(os.path.join(out_dir, "style_only_transfer.jpg"), out[0])

    # plt.plot(loss)
    # plt.savefig(os.path.join(out_dir, "style_loss.jpg"))

    # return out


  #############################################################################
  # unused?
  #############################################################################

  def set_initial_img(self, image):
    self.synthetic = self.vgg.toBGR(image)


  def open_image(self, image_path):
    image = utils.load_image2(image_path, self.width, self.height)
    return image.reshape((1, self.width, self.height, 3,))
