import random
random.seed(0)
import numpy as np
np.random.seed(0)
import tensorflow as tf
import onnx_graphsurgeon as gs
from utils.colors import Color
from typing import Any, List
from collections import namedtuple


def get_constant_or_variable(
    const_or_var: Any,
) -> Any:
    """Get a Numpy constant or gs.Variable from graph_surgeon node.

    Parameters
    ----------
    const_or_var: gs.Variable
        gs.Variable

    Returns
    ----------
    const_or_var:
        Numpy array or gs.Variable
    """
    if hasattr(const_or_var, 'values'):
        values = const_or_var.values
        tensor_rank = values.ndim
        if tensor_rank > 2:
            convertion_table = [0] + [i for i in range(2, tensor_rank - 2)] + [1]
            values = values.transpose(convertion_table)
        return values
    else:
        return const_or_var


# https://github.com/onnx/onnx-tensorflow/blob/main/onnx_tf/common/tf_helper.py
def tf_shape(
    *,
    input_tensor: tf.Tensor,
    dtype: tf.dtypes=tf.int64,
) -> Any:
    """Helper function returning the shape of a Tensor.

    Parameters
    ----------
    input_tensor: tf.Tensor
        A Tensor

    dtype: tf.dtypes
        The output dtype (tf.int32 or tf.int64).
        Defaults: tf.int64.

    Returns
    ----------
    shape:
        The function will check for fully defined shape and will return numpy array or \n
        if the shape is not fully defined will use tf.shape() to return the shape as a Tensor.
    """
    if input_tensor.shape.is_fully_defined():
        return np.array(input_tensor.shape.as_list(), dtype=dtype.as_numpy_dtype)
    else:
        return tf.shape(input_tensor, out_type=dtype)


def convert_axis(
    *,
    axis: int,
    tensor_rank: int,
) -> int:
    """Convert axis from NCW to NWC or NCHW to NHWC or NCDHW to NDHWC.

    Parameters
    ----------
    axis: int
        Axis value to be replaced

    tensor_rank: int
        Number of ranks of ex-tensors specified by axis

    Returns
    ----------
    converted_axis: int
        Converted axis
    """
    # Convert a negative number of axis to a positive number
    converted_axis = axis if axis >= 0 else axis + tensor_rank

    # 3D and 4D and 5D axis conversion table
    """
    convertion_table_3d = [0,2,1]
    convertion_table_4d = [0,3,1,2]
    convertion_table_5d = [0,4,1,2,3]
    convertion_table_6d = [0,5,1,2,3,4]
        :
    """
    if tensor_rank > 2:
        convertion_table = [0] + [tensor_rank - 1] + [i for i in range(1, tensor_rank - 1)]
        converted_axis = convertion_table[converted_axis]

    return converted_axis


def _nnapi_scalar(
    value,
    dtype: tf.dtypes,
) -> Any:
    """Scalar to constant of 1D array.

    Parameters
    ----------
    value: Tensor
        Tensor to be processed

    dtype: tf.dtypes
        Tensor type

    Returns
    ----------
    tensor: Tensor
        Tensor converted from Scalar to constant of 1D array
    """
    return tf.constant(value, dtype=dtype, shape=(1,))


def alternative_argmax(
    *,
    input_tensor,
    axis: int = -1,
    output_type: tf.dtypes = tf.dtypes.float32,
    name: str = None,
    keepdims: bool = False,
    epsilon: float = None,
    replace_argmax_to_reducemax_and_indicies_is_int64: bool = False,
    replace_argmax_to_reducemax_and_indicies_is_float32: bool = False,
) -> Any:
    """Replace ArgMax with a ReduceMax.

    Parameters
    ----------
    input_tensor: Tensor
        Tensor to be processed

    axis: int
        The axis to reduce across
        Default: -1

    output_type: tf.dtypes
        Data type of the final OP
        Default: tf.dtypes.float32

    name: str
        OP name to be assigned to the final OP
        Default: None

    keepdims: bool
        True: Array dimensionality is preserved after ArgMax
        False: Number of array dimensions not maintained after ArgMax
        Default: False

    epsilon: float
        Very small numbers added to avoid division by zero
        Default: None

    replace_argmax_to_reducemax_and_indicies_is_int64: bool
        True: Convert final output to int64
        False: Do not convert final output to int64
        Default: False

    replace_argmax_to_reducemax_and_indicies_is_float32: bool
        True: Convert final output to float32
        False: Do not convert final output to float32
        Default: False

    Returns
    ----------
    pseudo_argmax: Tensor
        Converted ArgMax
    """
    safe_axis = axis

    if safe_axis < 0:
        safe_axis = len(input_tensor.shape) + safe_axis
    reduction_size = input_tensor.shape[axis]
    axis_max = tf.math.reduce_max(
        input_tensor,
        axis=axis,
        keepdims=True,
    )
    zero_if_max = tf.subtract(
        axis_max,
        input_tensor,
    )
    eps = epsilon if epsilon else 1e-6

    if input_tensor.dtype.is_floating:
        zero_if_max_else_eps = tf.math.minimum(
            _nnapi_scalar(eps, input_tensor.dtype),
            zero_if_max,
        )
        zero_if_max_else_one = zero_if_max_else_eps * _nnapi_scalar(1 / eps, input_tensor.dtype)
    elif input_tensor.dtype.is_integer:
        zero_if_max_else_one = tf.math.minimum(
            _nnapi_scalar(1, input_tensor.dtype),
            zero_if_max,
        )
    else:
        error_msg = f''+\
            f'{Color.RED}ERROR:{Color.RESET} ' +\
            f'Please specify epsilon for unknown input data type. '
        print(error_msg)
        assert False, error_msg

    zero_if_max_else_one = tf.cast(
        zero_if_max_else_one,
        dtype=output_type,
    )
    zero_if_max_else_one = zero_if_max_else_one
    one_if_max_else_zero = tf.math.subtract(
        _nnapi_scalar(1, output_type),
        zero_if_max_else_one,
    )
    rev_index = tf.range(
        reduction_size,
        0,
        -1,
        dtype=output_type,
    )
    for index in range(safe_axis + 1, len(input_tensor.shape)):
        rev_index = tf.expand_dims(
            rev_index,
            axis=index - safe_axis,
        )
    rev_index = rev_index
    rev_index_if_max_else_zero = tf.math.multiply(
        one_if_max_else_zero,
        rev_index,
    )
    reverse_argmax = tf.math.reduce_max(
        rev_index_if_max_else_zero,
        axis=axis,
        keepdims=keepdims,
    )

    if replace_argmax_to_reducemax_and_indicies_is_int64:
        return tf.cast(
            tf.math.subtract(
                _nnapi_scalar(reduction_size, output_type),
                reverse_argmax,
                name=name,
            ),
            dtype=tf.dtypes.int64,
        )
    elif replace_argmax_to_reducemax_and_indicies_is_float32:
        return tf.cast(
            tf.math.subtract(
                _nnapi_scalar(reduction_size, output_type),
                reverse_argmax,
                name=name,
            ),
            dtype=tf.dtypes.float32,
        )
    else:
        return tf.math.subtract(
            _nnapi_scalar(reduction_size, output_type),
            reverse_argmax,
            name=name,
        )


# https://zenn.dev/pinto0309/articles/8f6df1d2304395
def alternative_asin(
    *,
    input_tensor,
) -> Any:
    """Replace Asin with a pseudo_Asin.

    Parameters
    ----------
    input_tensor: Tensor
        Tensor to be processed

    Returns
    ----------
    pseudo_asin: Tensor
        Converted Asin
    """
    x_abs = None
    x_abs = tf.abs(input_tensor)
    neg = tf.math.divide(tf.math.multiply(tf.minimum(input_tensor, 0), -1), x_abs)
    x = x_abs
    y = tf.constant(-0.0187293)
    y = tf.math.multiply(y, x)
    y = tf.math.add(y, 0.0742610)
    y = tf.math.multiply(y, x)
    y = tf.math.subtract(y, 0.2121144)
    y = tf.math.multiply(y, x)
    y = tf.math.add(y, 1.5707288)
    y = tf.math.subtract(tf.math.multiply(3.14159265358979, 0.5), tf.math.multiply(tf.sqrt(tf.math.subtract(1.0, x)), y))
    pseudo_asin = tf.math.subtract(y, tf.math.multiply(tf.math.multiply(2, neg), y))
    return pseudo_asin


# https://zenn.dev/pinto0309/articles/8f6df1d2304395
def alternative_acos(
    *,
    input_tensor,
) -> Any:
    """Replace Acos with a pseudo_Acos.

    Parameters
    ----------
    input_tensor: Tensor
        Tensor to be processed

    Returns
    ----------
    pseudo_acos: Tensor
        Converted Acos
    """
    x_abs = None
    x_abs = tf.abs(input_tensor)
    neg = tf.math.divide(tf.math.multiply(tf.minimum(input_tensor, 0), -1), x_abs)
    x = x_abs
    y = tf.constant(-0.0187293)
    y = tf.math.multiply(y, x)
    y = tf.math.add(y, 0.0742610)
    y = tf.math.multiply(y, x)
    y = tf.math.subtract(y, 0.2121144)
    y = tf.math.multiply(y, x)
    y = tf.math.add(y, 1.5707288)
    y = tf.math.multiply(y, tf.sqrt(tf.math.subtract(1.0, x)))
    y = tf.math.multiply(y, tf.math.subtract(1.0, tf.math.multiply(2.0, neg)))
    pseudo_acos = tf.math.add(tf.math.multiply(neg, 3.14159265358979), y)
    return pseudo_acos


# https://github.com/onnx/onnx-tensorflow/blob/main/onnx_tf/common/pooling_helper.py
pad_ops = namedtuple(
    "pad_ops",
    ["max_op", "ceil_op", "floor_op", "cast_int_op"]
)
pad_numpy_ops = pad_ops(
    np.maximum,
    np.ceil,
    np.floor,
    lambda arr: arr.astype(np.int64)
)
pad_tf_ops = pad_ops(
    tf.maximum,
    tf.math.ceil,
    tf.math.floor,
    lambda tensor: tf.cast(tensor, tf.int64)
)

def calc_pads_same_pooling(
    *,
    in_spatial_shape,
    kernel_shape,
    strides,
    dilations,
    padding,
    padding_ops=pad_numpy_ops,
    pads_order=1
) -> List[int]:
    """Calculates the SAME paddings that need to be added to the input.

    Parameters
    ----------
    in_spatial_shape:
        input spatial shape

    kernel_shape:
        the size of the kernel along each axis

    strides:
        stride along each spatial axis

    dilations:
        dilations value along each spatial axis

    padding:
        padding to calculate: SAME_UPPER orSAME_LOWER

    padding_ops:
        namedtuple with ops to be used during calculations.\n
        there are two sets of ops defined pad_numpy_ops and pad_tf_ops with numpy and tensorflow ops

    pads_order:
        order of returned pads.\n
        possible options are:\n
            1 - b1, b2, ..., bn, e1, e2, ..., en\n
            2 - b1, e1, b2, e2, ..., bn, en\n
        where n = len(kernel_shape) * 2, b1, b2, ..., bn\n
        define pads at the begging of axis e1, e2, ..., en define pads at the end of axis

    Returns
    ----------
    pads:
        array with calculated pads. the order of the values is determined by `pads_order`
    """
    spatial_size = len(kernel_shape)
    pads = [0] * (spatial_size * 2)
    for i in range(spatial_size):
        in_size = in_spatial_shape[i]
        filter_size = (kernel_shape[i] - 1) * dilations[i] + 1

        out_size = padding_ops.ceil_op(in_size / strides[i])
        out_size = padding_ops.cast_int_op(out_size)
        pad_along_axis = \
            padding_ops.max_op((out_size - 1) * strides[i] + filter_size - in_size, 0)
        if padding.lower() == "same_lower":
            pad_op = padding_ops.ceil_op
        else:
            pad_op = padding_ops.floor_op
        pad_begin = pad_op(pad_along_axis / 2)

        pad_begin = padding_ops.cast_int_op(pad_begin)
        pad_along_axis = padding_ops.cast_int_op(pad_along_axis)

        pad_end = pad_along_axis - pad_begin

        pads[i * pads_order] = pad_begin
        pads[i * pads_order + (spatial_size if pads_order == 1 else 1)] = pad_end

    return pads


def calc_pads_explicit_pooling(
    *,
    padding,
    spatial_size,
):
    """
    Calculate explicit padding
    """
    assert type(padding) is list

    pads = []
    for i in range(spatial_size):
        pads += [padding[i], padding[i + spatial_size]]
    return pads


def calc_pads_ceil_mode_pooling(
    *,
    in_spatial_shape,
    spatial_size,
    kernel_shape,
    dilations,
    strides,
    is_known_shape,
):
    """
    Calculate padding in ceil_mode
    """
    pads = []
    for i in range(spatial_size):
        dim_size = in_spatial_shape[i]
        filter_size = (kernel_shape[i] - 1) * dilations[i] + 1
        out_size = (dim_size - filter_size) / strides[i]
        if is_known_shape:
            pad_size = (np.ceil(out_size) - np.floor(out_size)).astype(np.int64)
        else:
            pad_size = tf.cast(tf.math.ceil(out_size) - tf.math.floor(out_size), tf.int64)

        pads += [0, pad_size * strides[i]]
    return pads


def calc_pads_same_pooling(
    *,
    kernel_shape,
    strides,
    dilations,
    padding,
    in_spatial_shape,
    is_known_shape,
):
    """
    Calculate SAME_* paddings.
    """
    pad_ops = pad_numpy_ops if is_known_shape else pad_tf_ops

    return calc_pads_same_pooling(
        in_spatial_shape=in_spatial_shape,
        kernel_shape=kernel_shape,
        strides=strides,
        dilations=dilations,
        padding=padding,
        padding_ops=pad_ops,
        pads_order=2,
    )


def calc_pads_pooling(
    *,
    kernel_shape,
    strides,
    dilations,
    padding,
    is_known_shape,
    spatial_size,
    in_spatial_shape,
    ceil_mode,
):
    if is_known_shape:
        pads = np.zeros([spatial_size * 2], np.int64)
    else:
        pads = tf.zeros([spatial_size * 2], tf.int64)

    # check for explicit padding
    if type(padding) is list:
        pads += calc_pads_explicit_pooling(
            padding=padding,
            spatial_size=spatial_size,
        )
    elif padding.lower().startswith("same"):
        pads += calc_pads_same_pooling(
            kernel_shape=kernel_shape,
            strides=strides,
            dilations=dilations,
            padding=padding,
            in_spatial_shape=in_spatial_shape,
            is_known_shape=is_known_shape,
        )

    # when padding is set to SAME, ceil_mode will not do anything
    # because output sizes will be multiple of the strides
    if ceil_mode and (type(padding) is list or not padding.lower().startswith("same")):
        new_spatial_shape = [
            in_spatial_shape[i] + pads[i * 2] + pads[i * 2 + 1]
            for i in range(spatial_size)
        ]
        pads += calc_pads_ceil_mode_pooling(
            in_spatial_shape=new_spatial_shape,
            spatial_size=spatial_size,
            kernel_shape=kernel_shape,
            dilations=dilations,
            strides=strides,
            is_known_shape=is_known_shape,
        )
    return pads


def pad_input(
    *,
    input_tensor,
    is_known_shape,
    kernel_shape,
    ceil_mode,
    spatial_size,
    strides,
    dilations,
    padding,
    padding_constant,
):
    """
    Pad the input according to the parameters
    """
    # check if we need to do any padding at all
    if not ceil_mode and ((type(padding) is list and padding == [0] * spatial_size * 2) or padding == "VALID"):
        return input_tensor

    # in_spatial_shape = self.input_shape[2:]
    input_shape = tf_shape(
        input_tensor=input_tensor,
    )
    in_spatial_shape = input_shape[1:len(kernel_shape)+1]
    pads = calc_pads_pooling(
        kernel_shape=kernel_shape,
        strides=strides,
        dilations=dilations,
        padding=padding,
        is_known_shape=is_known_shape,
        spatial_size=spatial_size,
        in_spatial_shape=in_spatial_shape,
        ceil_mode=ceil_mode,
    )

    if is_known_shape and np.count_nonzero(pads) == 0:
        return input_tensor

    # no padding on the NC dimensions
    tf_paddings = [[0, 0], [0, 0]]
    # padding for the (D)HW dimensions
    for i in range(spatial_size):
        tf_paddings += [[pads[i * 2], pads[i * 2 + 1]]]

    padded_tensor = tf.pad(
        input_tensor,
        tf_paddings,
        mode='CONSTANT',
        constant_values=padding_constant,
    )
    return padded_tensor