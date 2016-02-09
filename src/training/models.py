import numpy as np
import tensorflow as tf
import training.utils

def create_fully_connected_weights(input_size, num_labels, num_hidden_nodes):
    num_layers = len(num_hidden_nodes)
    layer_sizes = [*num_hidden_nodes, num_labels]

    weights = []
    prev_layer_size = input_size
    for cur_layer_size in layer_sizes:
        cur_weights = training.utils.gaussian_weights_variable(
            [prev_layer_size, cur_layer_size])
        cur_biases = tf.Variable(tf.zeros([cur_layer_size]))

        weights.append(cur_weights)
        weights.append(cur_biases)
        prev_layer_size = cur_layer_size

    return weights

def fully_connected_model(input_size, num_labels, num_hidden_nodes,
        valid_dataset, test_dataset, batch_size,
        learning_rate, beta = 0.0, dropout_prob = 0.0,
        exp_decay = None, method = 'gd'):
    """"""
    def create_model(weights, inputs, labels = None):
        hidden_units = inputs
        num_hidden_layers = len(weights) // 2 - 1
        regularisation_term = tf.zeros([1])

        for l in range(num_hidden_layers):
            cur_weights = weights[2*l]
            cur_biases = weights[2*l + 1]

            hidden_units = tf.nn.relu(tf.matmul(hidden_units, cur_weights) + cur_biases)
            if labels is not None:
                hidden_units = tf.nn.dropout(hidden_units, 1 - dropout_prob)

            regularisation_term = regularisation_term + tf.nn.l2_loss(cur_weights)

        # Output layer.
        cur_weights = weights[-2]
        cur_biases = weights[-1]
        out_logits = tf.matmul(hidden_units, cur_weights) + cur_biases
        out_prob = tf.nn.softmax(out_logits)
        regularisation_term = regularisation_term + tf.nn.l2_loss(cur_weights)

        if labels is not None:
            loss = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(out_logits, labels))
            loss = loss + beta * regularisation_term
            return out_prob, loss

        return out_prob

    graph = tf.Graph()
    with graph.as_default():
        tf_train_dataset = tf.placeholder(tf.float32, shape=(batch_size, input_size))
        tf_train_labels = tf.placeholder(tf.float32, shape=(batch_size, num_labels))
        tf_valid_dataset = tf.constant(valid_dataset)
        tf_test_dataset = tf.constant(test_dataset)

        # Variables.
        weights = create_fully_connected_weights(input_size, num_labels, num_hidden_nodes)

        # Training computation.
        train_prediction, loss = create_model(weights, tf_train_dataset, tf_train_labels)
        valid_prediction = create_model(weights, tf_valid_dataset)
        test_prediction = create_model(weights, tf_test_dataset)

        # Optimizer.
        global_step = tf.Variable(0)

        if exp_decay is not None:
            learning_rate = tf.train.exponential_decay(
                learning_rate, global_step,
                exp_decay['decay_steps'], exp_decay['decay_rate'], exp_decay['staircase'])

        optimizer = None
        if method == 'gd':
            optimizer = tf.train.GradientDescentOptimizer(learning_rate).minimize(
                loss, global_step=global_step)
        elif method == 'adagrad':
            optimizer = tf.train.AdagradOptimizer(learning_rate).minimize(
                loss, global_step=global_step)
        else:
            raise Exception('Unknown optimiser.')

    tf_graph = {
        'graph': graph,
        'data_ph': tf_train_dataset,
        'labels_ph': tf_train_labels }
    tf_predictions = [train_prediction, valid_prediction, test_prediction]

    return tf_graph, optimizer, loss, tf_predictions

# Skip-gram.
def skipgram_model(vocabulary_size, embedding_size, batch_size, num_sampled, valid_examples,
    learning_rate):
    graph = tf.Graph()
    with graph.as_default():
        # Input data.
        tf_train_dataset = tf.placeholder(tf.int32, shape=[batch_size])
        tf_train_labels = tf.placeholder(tf.int32, shape=[batch_size, 1])

        # Variables.
        embeddings = tf.Variable(tf.random_uniform([vocabulary_size, embedding_size], -1.0, 1.0))
        # This is actually transposed compared to usual layer weights. The std is
        # deduced accordingly, from the input size (embedding_size).
        softmax_weights = tf.Variable(tf.truncated_normal([vocabulary_size, embedding_size],
                               stddev=1.0 / np.sqrt(embedding_size)))
        softmax_biases = tf.Variable(tf.zeros([vocabulary_size]))

        # Model.
        # Look up embeddings for inputs.
        embed = tf.nn.embedding_lookup(embeddings, tf_train_dataset)
        # Compute the softmax loss, using a sample of the negative labels each time.
        loss = tf.reduce_mean(tf.nn.sampled_softmax_loss(
            softmax_weights, softmax_biases, embed, tf_train_labels, num_sampled, vocabulary_size))

        # Optimizer.
        optimizer = tf.train.AdagradOptimizer(learning_rate).minimize(loss)

        # Compute the similarity between minibatch examples and all embeddings.
        # We use the cosine distance:
        norm = tf.sqrt(tf.reduce_sum(tf.square(embeddings), 1, keep_dims=True))
        normalized_embeddings = embeddings / norm

        similarity = None
        if valid_examples is not None:
            valid_dataset = tf.constant(valid_examples, dtype=tf.int32)
            valid_embeddings = tf.nn.embedding_lookup(normalized_embeddings, valid_dataset)
            similarity = tf.matmul(valid_embeddings, tf.transpose(normalized_embeddings))

    tf_graph = {
        'graph': graph,
        'data_ph': tf_train_dataset,
        'labels_ph': tf_train_labels }

    return tf_graph, optimizer, loss, normalized_embeddings, similarity

def cbow_model(vocabulary_size, embedding_size, context_length, batch_size,
    num_sampled, valid_examples, learning_rate):
    input_batch_size = context_length * batch_size

    graph = tf.Graph()
    with graph.as_default():
        # Input data.
        tf_train_dataset = tf.placeholder(tf.int32, shape=[input_batch_size])
        tf_train_labels = tf.placeholder(tf.int32, shape=[batch_size, 1])

        word_mean_op = tf.constant(
            np.kron(np.eye(batch_size), np.ones([1, context_length])), dtype=tf.float32)

        # Variables.
        embeddings = tf.Variable(tf.random_uniform(
            [vocabulary_size, embedding_size], -1.0, 1.0))
        softmax_weights = tf.Variable(tf.truncated_normal(
            [vocabulary_size, embedding_size], stddev=1.0 / np.sqrt(embedding_size)))
        softmax_biases = tf.Variable(tf.zeros([vocabulary_size]))

        # Model.
        # Look up embeddings for inputs.
        embed = tf.nn.embedding_lookup(embeddings, tf_train_dataset)
        word_means = tf.matmul(word_mean_op, embed)
        # Compute the softmax loss, using a sample of the negative labels each time.
        loss = tf.reduce_mean(tf.nn.sampled_softmax_loss(
            softmax_weights, softmax_biases, word_means, tf_train_labels, num_sampled, vocabulary_size))

        # Optimizer.
        optimizer = tf.train.AdagradOptimizer(learning_rate).minimize(loss)

        # Compute the similarity between minibatch examples and all embeddings.
        # We use the cosine distance:
        norm = tf.sqrt(tf.reduce_sum(tf.square(embeddings), 1, keep_dims=True))
        normalized_embeddings = embeddings / norm

        similarity = None
        if valid_examples is not None:
            valid_dataset = tf.constant(valid_examples, dtype=tf.int32)
            valid_embeddings = tf.nn.embedding_lookup(normalized_embeddings, valid_dataset)
            similarity = tf.matmul(valid_embeddings, tf.transpose(normalized_embeddings))

    tf_graph = {
        'graph': graph,
        'data_ph': tf_train_dataset,
        'labels_ph': tf_train_labels }

    return tf_graph, optimizer, loss, normalized_embeddings, similarity
