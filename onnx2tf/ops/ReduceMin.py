import random
random.seed(0)
import numpy as np
np.random.seed(0)
import tensorflow as tf
import onnx_graphsurgeon as gs
from utils.common_functions import (
    convert_axis,
    get_constant_or_variable,
)


def make_node(
    *,
    graph_node: gs.Node,
    tf_layers_dict: dict,
    **kwargs: dict,
):
    """ReduceMin

    Parameters
    ----------
    graph_node: gs.Node
        graph_surgeon Node

    tf_layers_dict: dict
        optype, shape, dtype, tensorflow graph
    """
    graph_node_input = get_constant_or_variable(graph_node.inputs[0])
    graph_node_output: gs.Variable = graph_node.outputs[0]
    shape = graph_node_output.shape
    dtype = graph_node_output.dtype

    tensor_rank = len(graph_node_input.shape)

    axes = graph_node.attrs.get('axes', [-1])
    # NCHW->NHWC, NCDHW->NDHWC
    axes = convert_axis(
        axis=axes,
        tensor_rank=tensor_rank,
    )
    axes = [convert_axis(axis=idx, tensor_rank=tensor_rank) for idx in axes]

    # 0: False, 1: True
    keepdims = bool(graph_node.attrs.get('keepdims', 1))

    # Preserving Graph Structure (Dict)
    tf_layers_dict[graph_node_output.name] = {
        'optype': graph_node.op,
        'shape': shape,
        'dtype': dtype,
    }

    # Generation of TF OP
    reducemined_tensor = tf_layers_dict[graph_node_input.name]['tf_node'] \
        if isinstance(graph_node_input, gs.Variable) else graph_node_input
    for idx in axes:
        reducemined_tensor = tf.math.reduce_min(
            input_tensor=reducemined_tensor,
            axis=idx,
            keepdims=keepdims,
            name=f'{graph_node.name}_{idx}',
        )
    tf_layers_dict[graph_node_output.name]['tf_node'] = reducemined_tensor