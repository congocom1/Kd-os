"""
JARVIS Tiny ML Engine — a from-scratch neural network in pure numpy.

No external ML framework required. A small, transparent feedforward network
with backpropagation that JARVIS can train on camera frames (via the vision
learner plugin) and use to classify what it sees.

Architecture: input -> hidden layers -> output, sigmoid/ReLU activations,
mean-squared-error loss, stochastic gradient descent.

Weights are saved to/loaded from a single .npz file so learning persists
between sessions. Everything is intentional and inspectable — no black box.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

__all__ = [
    "TinyML", "TinyMLConfig",
]


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -500, 500)))


def _sigmoid_prime(y: np.ndarray) -> np.ndarray:
    return y * (1.0 - y)


def _relu(x: np.ndarray) -> np.ndarray:
    return np.maximum(0.0, x)


def _relu_prime(y: np.ndarray) -> np.ndarray:
    return (y > 0).astype(np.float32)


def _softmax(x: np.ndarray) -> np.ndarray:
    x = x - np.max(x, axis=-1, keepdims=True)
    e = np.exp(x)
    return e / np.sum(e, axis=-1, keepdims=True)


class TinyMLConfig:
    """Hyperparameters for the tiny network."""

    def __init__(
        self,
        layer_sizes: tuple[int, ...] = (64, 32, 10),
        learning_rate: float = 0.1,
        hidden_activation: str = "relu",
        output_activation: str = "softmax",
        seed: int = 42,
    ):
        self.layer_sizes = tuple(layer_sizes)
        self.learning_rate = float(learning_rate)
        self.hidden_activation = hidden_activation
        self.output_activation = output_activation
        self.seed = int(seed)


class TinyML:
    """A tiny trainable neural network.

    Usage:
        ml = TinyML(TinyMLConfig((64, 32, 3)))
        ml.train(X, y, epochs=100)          # X: (N, features), y: (N, classes)
        pred = ml.predict(X)                 # (N,) class indices
        ml.save("my_model.npz")
        ml2 = TinyML.load("my_model.npz")
    """

    def __init__(self, config: TinyMLConfig | None = None):
        self.config = config or TinyMLConfig()
        self.rng = np.random.default_rng(self.config.seed)
        self.weights: list[np.ndarray] = []
        self.biases: list[np.ndarray] = []
        self._initialized = False
        self.trained_epochs = 0
        self.history: list[float] = []

    # ── initialization ──────────────────────────────────────────────────────

    def _init_weights(self, n_inputs: int) -> None:
        """He initialization for hidden layers, Xavier for the output."""
        sizes = (n_inputs,) + self.config.layer_sizes
        self.weights = []
        self.biases = []
        for i in range(len(sizes) - 1):
            fan_in, fan_out = sizes[i], sizes[i + 1]
            if i < len(sizes) - 2:
                # hidden layer — He init
                std = math.sqrt(2.0 / fan_in)
            else:
                # output layer — Xavier
                std = math.sqrt(1.0 / fan_in)
            self.weights.append(self.rng.normal(0, std, size=(fan_in, fan_out)).astype(np.float32))
            self.biases.append(np.zeros(fan_out, dtype=np.float32))
        self._initialized = True

    # ── forward / backward ──────────────────────────────────────────────────

    def _forward(self, x: np.ndarray) -> tuple[list[np.ndarray], list[np.ndarray]]:
        """Return (activations, pre_activations) for a single sample."""
        activations = [x]
        pre_activations = []
        a = x
        n_layers = len(self.weights)
        for i in range(n_layers):
            z = a @ self.weights[i] + self.biases[i]
            pre_activations.append(z)
            if i == n_layers - 1:
                if self.config.output_activation == "softmax":
                    a = _softmax(z)
                else:
                    a = _sigmoid(z)
            else:
                if self.config.hidden_activation == "relu":
                    a = _relu(z)
                else:
                    a = _sigmoid(z)
            activations.append(a)
        return activations, pre_activations

    def _backward(
        self,
        activations: list[np.ndarray],
        pre_activations: list[np.ndarray],
        target: np.ndarray,
    ) -> None:
        """One step of backpropagation, updating weights in place."""
        n_layers = len(self.weights)
        # output error
        if self.config.output_activation == "softmax":
            # cross-entropy + softmax derivative simplifies to (a - y)
            delta = (activations[-1] - target)
        else:
            delta = (activations[-1] - target) * _sigmoid_prime(activations[-1])

        grads_w = [None] * n_layers
        grads_b = [None] * n_layers

        for i in range(n_layers - 1, -1, -1):
            grads_w[i] = np.outer(activations[i], delta)
            grads_b[i] = delta
            if i > 0:
                if self.config.hidden_activation == "relu":
                    delta = (delta @ self.weights[i].T) * _relu_prime(activations[i])
                else:
                    delta = (delta @ self.weights[i].T) * _sigmoid_prime(activations[i])

        lr = self.config.learning_rate
        for i in range(n_layers):
            self.weights[i] -= lr * grads_w[i]
            self.biases[i] -= lr * grads_b[i]

    # ── public API ──────────────────────────────────────────────────────────

    def train(self, X: np.ndarray, y: np.ndarray, epochs: int = 100) -> list[float]:
        """Train on (X, y). X is (N, features); y is (N, classes) one-hot or
        (N,) class indices. Returns loss history."""
        if not self._initialized:
            self._init_weights(X.shape[1])

        X = np.asarray(X, dtype=np.float32)
        y = np.asarray(y)
        n_samples = X.shape[0]

        # one-hot encode if needed
        if y.ndim == 1:
            n_classes = self.config.layer_sizes[-1]
            y_onehot = np.zeros((n_samples, n_classes), dtype=np.float32)
            y_onehot[np.arange(n_samples), y.astype(int)] = 1.0
            y = y_onehot
        else:
            y = y.astype(np.float32)

        history = []
        for epoch in range(int(epochs)):
            perm = self.rng.permutation(n_samples)
            epoch_loss = 0.0
            for idx in perm:
                activations, _ = self._forward(X[idx])
                epoch_loss += float(np.mean((activations[-1] - y[idx]) ** 2))
                self._backward(activations, [], y[idx])
            epoch_loss /= n_samples
            history.append(epoch_loss)
        self.history.extend(history)
        self.trained_epochs += int(epochs)
        return history

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Return predicted class indices for X (N, features)."""
        X = np.asarray(X, dtype=np.float32)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        if not self._initialized:
            raise RuntimeError("TinyML has not been initialized — call train() first.")
        # batch
        all_probs = []
        for i in range(len(X)):
            all_probs.append(self._forward(X[i])[0][-1])
        all_probs = np.stack(all_probs)
        return np.argmax(all_probs, axis=1)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Return class probabilities for X."""
        X = np.asarray(X, dtype=np.float32)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        all_probs = [self._forward(x)[0][-1] for x in X]
        return np.stack(all_probs)

    def accuracy(self, X: np.ndarray, y: np.ndarray) -> float:
        """Fraction correct on (X, y). y can be class indices or one-hot."""
        preds = self.predict(X)
        y = np.asarray(y)
        if y.ndim > 1:
            y = np.argmax(y, axis=1)
        return float(np.mean(preds == y.astype(int)))

    # ── persistence ─────────────────────────────────────────────────────────

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        kv: dict = {
            "layer_sizes": np.array(self.config.layer_sizes),
            "learning_rate": np.array([self.config.learning_rate]),
            "trained_epochs": np.array([self.trained_epochs]),
            "n_layers": np.array([len(self.weights)]),
        }
        for i, w in enumerate(self.weights):
            kv[f"w_{i}"] = w
        for i, b in enumerate(self.biases):
            kv[f"b_{i}"] = b
        np.savez(path, **kv)

    @classmethod
    def load(cls, path: str | Path) -> "TinyML":
        path = Path(path)
        data = np.load(path, allow_pickle=True)
        layer_sizes = tuple(int(v) for v in data["layer_sizes"])
        lr = float(data["learning_rate"][0])
        epochs = int(data["trained_epochs"][0])
        config = TinyMLConfig(layer_sizes=layer_sizes, learning_rate=lr)
        ml = cls(config)
        n_layers = int(data["n_layers"][0])
        ml.weights = [data[f"w_{i}"].astype(np.float32) for i in range(n_layers)]
        ml.biases = [data[f"b_{i}"].astype(np.float32) for i in range(n_layers)]
        ml._initialized = True
        ml.trained_epochs = epochs
        return ml
