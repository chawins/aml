from scipy import ndimage as ndi
from skimage.feature import canny

from parameters import *
from lib.keras_utils import *

# Threshold for checking mask area
MASK_THRES_MIN = 0.1
MASK_THRES_MAX = 0.9


def rgb2gray(image):
    """Convert 3-channel RGB image into grayscale"""
    return (0.299 * image[:, :, 0] + 0.587 * image[:, :, 1] +
            0.114 * image[:, :, 2])


def read_image(im_name):
    """Read a single image into numpy array"""
    return misc.imread(im_name, flatten=False, mode='RGB')


def read_images(path, resize=False, interp='bilinear'):
    """
    Read all image files in a directory, resize to 32 x 32 pixels if
    specified. Return array of images with same format as read from
    load_dataset(). Chosen interpolation algorithm may affect the result
    (default: bilinear). Images are scaled to [0, 1]
    """

    imgs = []
    valid_images = [".jpg", ".gif", ".png", ".tga", ".jpeg"]
    for f in sorted(os.listdir(path)):
        ext = os.path.splitext(f)[1]
        if ext.lower() not in valid_images:
            continue
        im = read_image(os.path.join(path, f))
        if resize:
            im = misc.imresize(im, (32, 32), interp=interp)
        im = (im / 255.).astype(np.float32)
        imgs.append(im)
    return np.array(imgs)


def read_labels(path):
    """Read labels to a list"""

    with open(path) as f:
        content = f.readlines()
    content = [int(x.strip()) for x in content]
    return content


def resize(image, interp='bilinear'):
    """Resize to IMAGE_SIZE and rescale to [0, 1]"""

    img = misc.imresize(image, IMAGE_SIZE, interp=interp)
    img = (img / 255.).astype(np.float32)
    return img


def resize_all(images, interp='bilinear'):
    """Resize all images to IMAGE_SIZE"""

    if images[0].ndim == 3:
        shape = (len(images),) + IMAGE_SIZE + (N_CHANNEL,)
    else:
        shape = (len(images),) + IMAGE_SIZE
    images_rs = np.zeros(shape)
    for i, image in enumerate(images):
        images_rs[i] = resize(image, interp=interp)
    return images_rs


def check_mask(mask):
    """Check if mask is valid by its area"""

    area_ratio = np.sum(mask) / float(mask.shape[0] * mask.shape[1])
    return (area_ratio > MASK_THRES_MIN) and (area_ratio < MASK_THRES_MAX)


def load_samples(img_dir, label_path):
    """Load sample images, resize and find masks"""

    # Load images and labels
    images = read_images(img_dir)
    labels = read_labels(label_path)

    ex_ind = []
    masks_full = []

    for i, image in enumerate(images):
        # Find sign area from full-sized image
        mask = find_sign_area(rgb2gray(image))
        # Keep only valid mask
        if check_mask(mask):
            masks_full.append(mask)
        else:
            ex_ind.append(i)

    # Resize mask to IMAGE_SIZE
    masks = resize_all(masks_full, interp='nearest')

    # Exclude images that don't produce valid mask
    x_ben_full = np.delete(images, ex_ind, axis=0)
    y_ben = np.delete(labels, ex_ind, axis=0)

    # Resize images
    x_ben = resize_all(x_ben_full, interp='bilinear')

    # One-hot encode labels
    y_ben = keras.utils.to_categorical(y_ben, NUM_LABELS)

    return x_ben, x_ben_full, y_ben, masks, masks_full


def softmax(x):
    """
    Compute softmax values for each sets of scores in x.
    Ref: https://stackoverflow.com/questions/34968722/softmax-function-python
    """
    e_x = np.exp(x - np.max(x))
    return e_x / e_x.sum(axis=0)


def to_class(y):
    """
    Convert categorical (one-hot) to classes. Also works with softmax output
    """
    return np.argmax(y, axis=1)


def load_dataset_GTSRB(n_channel=3, train_file_name=None):
    """
    Load GTSRB data as a (datasize) x (channels) x (height) x (width) numpy
    matrix. Each pixel is rescaled to lie in [0,1].
    """

    def load_pickled_data(file, columns):
        """
        Loads pickled training and test data.

        Parameters
        ----------
        file    : string
                          Name of the pickle file.
        columns : list of strings
                          List of columns in pickled data we're interested in.

        Returns
        -------
        A tuple of datasets for given columns.
        """

        with open(file, mode='rb') as f:
            dataset = pickle.load(f)
        return tuple(map(lambda c: dataset[c], columns))

    def preprocess(x, n_channel):
        """
        Preprocess dataset: turn images into grayscale if specified, normalize
        input space to [0,1], reshape array to appropriate shape for NN model
        """

        if n_channel == 3:
            # Scale features to be in [0, 1]
            x = (x / 255.).astype(np.float32)
        else:
            # Convert to grayscale, e.g. single Y channel
            x = 0.299 * x[:, :, :, 0] + 0.587 * x[:, :, :, 1] + \
                0.114 * x[:, :, :, 2]
            # Scale features to be in [0, 1]
            x = (x / 255.).astype(np.float32)
            x = x[:, :, :, np.newaxis]
        return x

    # Load pickle dataset
    if train_file_name is None:
        x_train, y_train = load_pickled_data(
            DATA_DIR + 'train.p', ['features', 'labels'])
    else:
        x_train, y_train = load_pickled_data(
            DATA_DIR + train_file_name, ['features', 'labels'])
    x_val, y_val = load_pickled_data(
        DATA_DIR + 'valid.p', ['features', 'labels'])
    x_test, y_test = load_pickled_data(
        DATA_DIR + 'test.p', ['features', 'labels'])

    # Preprocess loaded data
    x_train = preprocess(x_train, n_channel)
    x_val = preprocess(x_val, n_channel)
    x_test = preprocess(x_test, n_channel)
    return x_train, y_train, x_val, y_val, x_test, y_test


def filter_samples(model, x, y, y_target=None):
    """
    Returns samples and their corresponding labels that are correctly classified 
    by the model and are not classified as target if specified.

    Parameters
    ----------
    model    : Keras Model
               Model to consider
    x        : np.array, shape=(n_sample, height, width, n_channel)
               Samples to filter
    y        : np.array, shape=(n_sample, NUM_LABELS)
               Corresponding true labels of x. Must be one-hot encoded.
    y_target : (optional) np.array, shape=(n_sample, NUM_LABELS)
               Specified if you want to also exclude samples that are 
               classified as target

    Return
    ------
    Tuple of two np.array's, filtered samples and their corresponding labels
    """

    y_ = to_class(model.predict(x))
    y_true = to_class(y)
    del_id = np.array(np.where(y_ != y_true))[0]

    # If target is specified, remove samples that are originally classified as
    # target
    if y_target is not None:
        y_tg = to_class(y_target)
        del_id = np.concatenate((del_id, np.array(np.where(y_ == y_tg))[0]))

    del_id = np.sort(np.unique(del_id))
    return np.delete(x, del_id, axis=0), np.delete(y, del_id, axis=0), del_id


def eval_adv(model, x_adv, y, target=True):
    """
    Evaluate adversarial examples

    Parameters
    ----------
    model  : Keras model
             Target model
    x_adv  : np.array, shape=(n_mag, n_sample, height, width, n_channel) or 
             shape=(n_sample, height, width, n_channel)
             Adversarial examples to evaluate
    y      : np.array, shape=(n_sample, NUM_LABELS)
             Target label for each of the sample in x if target is True.
             Otherwise, corresponding labels of x. Must be one-hot encoded.
    target : (optional) bool
             True, if targeted attack. False, otherwise.

    Return
    ------
    suc_rate : list
               Success rate of attack
    """

    n_sample = len(y)
    y_t = to_class(y)

    if x_adv.ndim == 4:
        y_ = to_class(model.predict(x_adv))
        if target:
            return np.sum(y_t == y_) / float(n_sample)
        else:
            return np.sum(y_t != y_) / float(n_sample)
    elif x_adv.ndim == 5:
        suc_rate = []
        for _, x in enumerate(x_adv):
            y_ = to_class(model.predict(x))
            if target:
                suc_rate.append(np.sum(y_t == y_) / float(n_sample))
            else:
                suc_rate.append(np.sum(y_t != y_) / float(n_sample))
        return suc_rate
    else:
        print "Incorrect format for x_adv."
        return


def find_sign_area(image, sigma=1):
    """
    Use edge-based segmentation algorithm to find the area of the sign on a
    given image. Under the hood, it simply finds the largest recognizable
    closed shape. sigma need to be adjusted in some cases. The code is taken
    from:
    http://scikit-image.org/docs/dev/user_guide/tutorial_segmentation.html
    """

    edges = canny(image, sigma=sigma)
    fill = ndi.binary_fill_holes(edges)
    label_objects, _ = ndi.label(fill)
    sizes = np.bincount(label_objects.ravel())
    mask_sizes = np.zeros_like(sizes)
    sizes[0] = 0
    mask_sizes[np.argmax(sizes)] = 1.
    cleaned = mask_sizes[label_objects]

    return cleaned


def fg(model, x, y, mag_list, target=True, mask=None):
    """
    Fast Gradient attack. Similar to iterative attack but only takes one step
    and then clip result afterward.

    Parameters
    ----------
    model    : Keras Model
               Model to attack
    x        : np.array, shape=(n_sample, height, width, n_channel)
               Benign samples to attack
    y        : np.array, shape=(n_sample, NUM_LABELS)
               Target label for each of the sample in x if target is True.
               Otherwise, corresponding labels of x. Must be one-hot encoded.
    mag_list : list of float
               List of perturbation magnitude to use in the attack
    target   : (optional) bool
               True, if targeted attack. False, otherwise.
    mask     : (optional) np.array of 0 or 1, shape=(n_sample, height, width)
               Mask to restrict gradient update on valid pixels

    Return
    ------
    x_adv    : np.array, shape=(n_mag, n_sample, height, width, n_channel)
               Adversarial examples
    """

    x_adv = np.zeros((len(mag_list),) + x.shape, dtype=np.float32)
    grad_fn = gradient_fn(model)
    start_time = time.time()

    for i, x_in in enumerate(x):

        # Retrieve gradient
        if target:
            grad = -1 * gradient_input(grad_fn, x_in, y[i])
        else:
            grad = gradient_input(grad_fn, x_in, y[i])

        # Apply mask
        if mask is not None:
            mask_rep = np.repeat(mask[i, :, :, np.newaxis], N_CHANNEL, axis=2)
            grad *= mask_rep

        # Normalize gradient
        try:
            grad /= np.linalg.norm(grad)
        except ZeroDivisionError:
            raise

        for j, mag in enumerate(mag_list):
            x_adv[j, i] = x_in + grad * mag

        # Progress printing
        if (i % 1000 == 0) and (i > 0):
            elasped_time = time.time() - start_time
            print "Finished {} samples in {:.2f}s.".format(i, elasped_time)
            start_time = time.time()

    # Clip adversarial examples to stay in range [0, 1]
    x_adv = np.clip(x_adv, 0, 1)

    return x_adv


def iterative(model, x, y, n_step=20, step_size=0.05, target=True, mask=None):
    """
    Iterative attack. Move a benign sample in the gradient direction one small
    step at a time for <n_step> times. Clip values after each step.

    Parameters
    ----------
    model     : Keras Model
                Model to attack
    x         : np.array, shape=(n_sample, height, width, n_channel)
                Benign samples to attack
    y         : np.array, shape=(n_sample, NUM_LABELS)
                Target label for each of the sample in x if target is True.
                Otherwise, corresponding labels of x. Must be one-hot encoded.
    n_step    : (optional) int
                Number of iteration to take
    step_size : (optional) float
                Magnitude of perturbation in each iteration
    target    : (optional) bool
                True, if targeted attack. False, otherwise.
    mask      : (optional) np.array of 0 or 1, shape=(n_sample, height, width)
                Mask to restrict gradient update on valid pixels

    Return
    ------
    x_adv    : np.array, shape=(n_mag, n_sample, height, width, n_channel)
               Adversarial examples
    """

    x_adv = np.zeros(x.shape, dtype=np.float32)
    grad_fn = gradient_fn(model)
    start_time = time.time()

    for i, x_in in enumerate(x):

        x_cur = np.copy(x_in)
        # Get mask with the same shape as gradient
        if mask is not None:
            mask_rep = np.repeat(mask[i, :, :, np.newaxis], N_CHANNEL, axis=2)
        # Start update in steps
        for _ in range(n_step):
            if target is not None:
                grad = -1 * gradient_input(grad_fn, x_cur, y[i])
            else:
                grad = gradient_input(grad_fn, x_cur, y[i])

            # Apply mask
            if mask is not None:
                grad *= mask_rep

            # Normalize gradient
            try:
                grad /= np.linalg.norm(grad)
            except ZeroDivisionError:
                raise

            x_cur += grad * step_size
            # Clip to stay in range [0, 1]
            x_cur = np.clip(x_cur, 0, 1)

        x_adv[i] = np.copy(x_cur)

        # Progress printing
        if (i % 200 == 0) and (i > 0):
            elasped_time = time.time() - start_time
            print "Finished {} samples in {:.2f}s.".format(i, elasped_time)
            start_time = time.time()

    return x_adv
