# Copyright (C) 2013  Hannes Bretschneider

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

import hebel
hebel.init(0)

import unittest
import random
import numpy as np
from pycuda import gpuarray
from pycuda.curandom import rand as curand
from hebel import sampler
from hebel.models import NeuralNet, NeuralNetRegression
from hebel.optimizers import SGD
from hebel.parameter_updaters import SimpleSGDUpdate, \
    MomentumUpdate, NesterovMomentumUpdate
from hebel.data_providers import MNISTDataProvider, BatchDataProvider
from hebel.monitors import SimpleProgressMonitor
from hebel.schedulers import exponential_scheduler, linear_scheduler_up, \
    constant_scheduler
from hebel.pycuda_ops.matrix import extract_columns, insert_columns
from hebel.pycuda_ops.elementwise import sample_dropout_mask


class TestNeuralNetMNIST(unittest.TestCase):
    def setUp(self):
        self.train_data = MNISTDataProvider('train', 100)
        self.test_data = MNISTDataProvider('test')
        self.D = self.train_data.D
        self.n_out = 10

    def test_relu(self):
        model = NeuralNet(n_in=self.D, n_out=self.n_out,
                          layers=[1000], activation_function='relu',
                          dropout=True)
        optimizer = SGD(model, SimpleSGDUpdate, self.train_data,
                        self.test_data,
                        learning_rate_schedule=exponential_scheduler(1., .99),
                        progress_monitor=SimpleProgressMonitor())
        optimizer.run(20)
        self.assertLess(optimizer.progress_monitor.train_error[-1][1],
                        optimizer.progress_monitor.train_error[0][1])
        del model, optimizer

    def test_momentum(self):
        model = NeuralNet(n_in=self.D, n_out=self.n_out,
                          layers=[1000], activation_function='relu',
                          dropout=True)
        optimizer = SGD(model, MomentumUpdate, self.train_data,
                        self.test_data,
                        learning_rate_schedule=exponential_scheduler(1., .99),
                        momentum_schedule=linear_scheduler_up(.5, .9, 5),
                        progress_monitor=SimpleProgressMonitor())
        optimizer.run(20)
        self.assertLess(optimizer.progress_monitor.train_error[-1][1],
                        optimizer.progress_monitor.train_error[0][1])
        del model, optimizer

    def test_nesterov_momentum(self):
        model = NeuralNet(n_in=self.D, n_out=self.n_out,
                          layers=[100], activation_function='relu',
                          dropout=True)
        optimizer = SGD(model, NesterovMomentumUpdate, self.train_data,
                        self.test_data,
                        learning_rate_schedule=exponential_scheduler(1., .99),
                        momentum_schedule=linear_scheduler_up(.5, .9, 5),
                        progress_monitor=SimpleProgressMonitor())
        optimizer.run(20)
        self.assertLess(optimizer.progress_monitor.train_error[-1][1],
                        optimizer.progress_monitor.train_error[0][1])
        del model, optimizer


class TestColumnSlicing(unittest.TestCase):
    def test_extract_columns(self):
        for _ in range(20):
            dtype = random.choice((np.float32, np.float64))
            N = np.random.randint(100, 1000)
            M = np.random.randint(100, 1000)
            a = np.random.randint(0, M)
            b = np.random.randint(a + 1, M)
            m = b - a
            assert m > 0

            X = curand((N, M), dtype)
            Y = extract_columns(X, a, b)

            self.assertTrue(np.all(X.get()[:, a:b] == Y.get()))

    def test_insert_columns(self):
        for _ in range(20):
            dtype = random.choice((np.float32, np.float64))
            N = np.random.randint(100, 1000)
            M = np.random.randint(100, 1000)
            m = np.random.randint(1, M)
            offset = np.random.randint(0, M - m)

            X = curand((N, M), dtype)
            Y = curand((N, m), dtype)
            insert_columns(Y, X, offset)

            self.assertTrue(np.all(X.get()[:, offset:offset+m] == Y.get()))


class TestSampleDropoutMask(unittest.TestCase):
    TOL = 1e-3

    def test_sample_dropout_mask(self):
        for _ in range(20):
            height = 1000
            width = 10000
            dropout_prob = np.random.rand()
            X = sampler.gen_uniform((height, width), np.float32)
            dropout_mask = sample_dropout_mask(X, dropout_prob)
            dropout_rate = 1. - dropout_mask.get().mean()

            self.assertLess(np.abs(dropout_prob - dropout_rate), self.TOL)
            self.assertTrue(np.all((X.get() != 0.) == dropout_mask.get()))

    def test_sample_dropout_mask_columns(self):
        for _ in range(20):
            height = 10000
            width = 10000
            dropout_prob = np.random.rand()
            X = sampler.gen_uniform((height, width), np.float32)

            start = np.random.randint(0, width - 1000)
            end = start + 1000
            columns = (start, end)

            dropout_mask = sample_dropout_mask(X, dropout_prob, columns)
            dropout_rate = 1. - dropout_mask.get().mean()

            self.assertEqual(dropout_mask.shape, (X.shape[0], end - start))
            self.assertLess(np.abs(dropout_prob - dropout_rate),
                            self.TOL)
            self.assertTrue(np.all((X.get()[:, start:end] != 0.)
                                   == dropout_mask.get()))

class TestNeuralNetRegression(unittest.TestCase):
    def test_neural_net_regression(self):
        for _ in range(20):
            N = 10000    # Number of data points
            D = 100      # Dimensionality of exogenous data
            P = 50       # Dimensionality of endogenous data

            W_true = 10 * np.random.rand(D, P) - 5
            b_true = 100 * np.random.rand(P) - 50

            X = np.random.randn(N, D)
            Y = np.dot(X, W_true) + b_true[np.newaxis, :] + np.random.randn(N, P)        

            W_lstsq = np.linalg.lstsq(np.c_[np.ones((N, 1)), X], Y)[0]
            b_lstsq = W_lstsq[0]
            W_lstsq = W_lstsq[1:]

            data_provider = BatchDataProvider(gpuarray.to_gpu(X.astype(np.float32)),
                                              gpuarray.to_gpu(Y.astype(np.float32)))

            model = NeuralNetRegression([], n_in=D, n_out=P)
            optimizer = SGD(model, SimpleSGDUpdate, 
                            data_provider, data_provider,
                            learning_rate_schedule=constant_scheduler(10.),
                            early_stopping=True)
            optimizer.run(100)

            self.assertLess(np.abs(W_lstsq - model.top_layer.W.get()).max(),
                            1e-5)
        
if __name__ == '__main__':
    unittest.main()
