import numpy as np
from docutils.nodes import topic
import tensorflow as tf
from tools import *
from tensorflow.keras import layers
from tensorflow.keras import Model

"""
BaseSolution is class for every vision -> action problem.
It's based on the Deep Deterministic Policy Gradient algorithm.
It was intended to make a base class that will be a foundation for more complex solutions, which can inherit it.
"""


class BaseSolution:
    def __init__(self, action_space, model_outputs=None):
        self.action_space = action_space
        # For problems that have specific outputs of an actor model
        self.need_decode_out = model_outputs is not None
        self.model_action_out = model_outputs if model_outputs else action_space.shape[0]

        self.noise = NoiseGenerator(np.full(self.model_action_out, 0.0, np.float32),
                                    np.full((self.model_action_out,), 0.001, np.float32))
        # Initialize buffer R
        self.r_buffer = MemoriesRecorder(memory_capacity=40000)

        self.actor = None
        self.critic = None
        self.target_actor = None
        self.target_critic = None

        # Hyperparameters
        self.gamma = 0.99

    def reset(self):
        self.noise.reset()

    def build_actor(self, state_shape, name="Actor"):
        inputs = layers.Input(shape=state_shape)
        x = inputs
        x = layers.Conv2D(32, kernel_size=(3, 3), padding='valid', use_bias=False, activation="relu")(inputs)
        x = layers.MaxPool2D(pool_size=(2, 2))(x)

        x = layers.Conv2D(64, kernel_size=(3, 3), padding='valid', use_bias=False, activation="relu")(x)
        x = layers.MaxPool2D(pool_size=(2, 2))(x)

        x = layers.Conv2D(64, kernel_size=(3, 3), padding='valid', use_bias=False, strides=(2, 2), activation="relu")(x)
        x = layers.AvgPool2D(pool_size=(2, 2))(x)

        x = layers.Flatten()(x)
        x = layers.Dense(64, activation='relu')(x)
        last_init = tf.random_uniform_initializer(minval=-0.005, maxval=0.005)
        y = layers.Dense(self.model_action_out, activation='sigmoid', kernel_initializer=last_init)(x)

        model = Model(inputs=inputs, outputs=y, name=name)
        model.summary()
        return model

    def build_critic(self, state_shape, name="Critic"):
        state_inputs = layers.Input(shape=state_shape)
        x = state_inputs
        x = layers.Conv2D(32, kernel_size=(3, 3), padding='valid', use_bias=False, activation="relu")(state_inputs)
        x = layers.MaxPool2D(pool_size=(2, 2))(x)

        x = layers.Conv2D(64, kernel_size=(3, 3), padding='valid', use_bias=False, activation="relu")(x)
        x = layers.MaxPool2D(pool_size=(2, 2))(x)

        x = layers.Conv2D(64, kernel_size=(3, 3), padding='valid', use_bias=False, strides=(2, 2), activation="relu")(x)
        x = layers.AvgPool2D(pool_size=(2, 2))(x)

        x = layers.Flatten()(x)
        action_inputs = layers.Input(shape=(self.model_action_out,))
        x = layers.concatenate([x, action_inputs])

        x = layers.Dense(64, activation='relu')(x)
        x = layers.Dense(32, activation='relu')(x)
        y = layers.Dense(1)(x)

        model = Model(inputs=[state_inputs, action_inputs], outputs=y, name=name)
        model.summary()
        return model

    def init_networks(self, state_shape):
        self.actor  = self.build_actor(state_shape)
        self.critic = self.build_critic(state_shape)

        # Build target networks in the same way
        self.target_actor  = self.build_actor(state_shape, name='TargetActor')
        self.target_critic = self.build_critic(state_shape, name='TargetCritic')

        # Copy parameters from action and critic
        self.target_actor.set_weights(self.actor.get_weights())
        self.target_critic.set_weights(self.critic.get_weights())

    def get_action(self, state):
        prep_state = self.preprocess(state)
        if self.actor is None:
            self.init_networks(prep_state.shape)

        # Get result from a network
        tensor_state = tf.expand_dims(tf.convert_to_tensor(prep_state), 0)
        actor_output = self.actor(tensor_state).numpy()

        # Add noise
        actor_output = actor_output[0] + self.noise.generate()

        if self.need_decode_out:
            env_action = self.decode_model_output(actor_output)
        else:
            env_action = actor_output

        # Clip min-max
        env_action = np.clip(np.array(env_action), a_min=self.action_space.low, a_max=self.action_space.high)
        return env_action, actor_output

    def decode_model_output(self, model_out):
        return np.array([model_out[0] - model_out[1], model_out[2], model_out[3]])

    def preprocess(self, img, greyscale=True):
        if greyscale:
            img = img.mean(axis=2)
            img = np.expand_dims(img, 2)

        # Normalize from -1. to 1.
        img = (img / img.max()) * 2 - 1
        return img

    def learn(self, state, train_action, reward, new_state):
        # Store transition in R
        prep_state     = self.preprocess(state)
        prep_new_state = self.preprocess(new_state)
        self.r_buffer.write(prep_state, train_action, reward, prep_new_state)

        # Sample mini-batch from R
        state_batch, action_batch, reward_batch, new_state_batch  = self.r_buffer.sample()

        # Calc y
        y = reward_batch + self.gamma * self.target_critic([new_state_batch, self.target_actor(new_state_batch)])

        # Update critic
        critic_loss = tf.reduce_mean(tf.square(y - self.critic([state_batch, action_batch])))

        # TODO: Update actor
        # TODO: Update target networks

