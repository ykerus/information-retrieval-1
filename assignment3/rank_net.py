import dataset
import ranking as rnk
import evaluate as evl

import torch
import torch.nn as nn
import numpy as np
from tqdm import tqdm
from time import time
from itertools import combinations

import pickle


class Rank_Net(nn.Module):
    def __init__(self, d_in, num_neurons=1, sigma=1.0, dropout=0.0, device='cpu'):
        assert isinstance(num_neurons, list) or isinstance(num_neurons, int), "num_neurons must be either an int (one layer) or a list of ints"
        if isinstance(num_neurons, int):
            num_neurons = [num_neurons]

        super(Rank_Net, self).__init__()
        self.d_in = d_in
        self.num_neurons = num_neurons
        self.num_neurons.insert(0, self.d_in)
        self.sigma = sigma
        self.dropout = dropout
        self.device = device
        self.model_id = np.random.randint(1000000, 9999999)
        layers = []
        for h, h_next in zip(num_neurons, num_neurons[1:]):
            layers.append(nn.Linear(h, h_next))
            layers.append(nn.Dropout(self.dropout))
            layers.append(nn.ReLU())
        layers.pop()
        layers.append(nn.ReLU6())
        self.layers = nn.Sequential(*layers)

    def forward(self, x):
        x = torch.from_numpy(x).float().to(self.device)
        self.layers.to(self.device)
        return self.layers(x)

    def train_bgd(self, data, lr=1e-3, batch_size=500, num_epochs=1, ndcg_convergence=0.95, eval_freq=1):
        self.layers.train()
        optimizer = torch.optim.Adam(self.layers.parameters(), lr=lr)

        num_queries = data.train.num_queries()
        converged = False
        for e in range(num_epochs):
            if converged:
                break
            print('start preparing batches ...')
            start = time()
            batches = self.prepare_batches(data.train, num_queries, batch_size)
            end = time()
            print('Prepared batches in {} seconds'.format(end-start))
            for b, (batch_data, batch_labels) in enumerate(batches):
                if converged:
                    break
                batch_scores = self.forward(batch_data)
                loss = 0.0
                for qid in tqdm(range(len(batch_labels))):
                    query_scores = batch_scores[qid]
                    query_labels = batch_labels[qid]
                    for i in range(len(query_scores)):
                        for j in range(len(query_scores)):
                            if i == j:
                                continue
                            loss += self.pair_cross_entropy(query_scores[i], query_scores[j], query_labels[i], query_labels[j])

                optimizer.zero_grad()
                loss /= batch_size
                loss.backward()
                optimizer.step()

                if eval_freq != 0:
                    if b % eval_freq == 0:
                        print('Average Loss: {} for batch {} of {} batches'.format(loss, b, len(batches)))
                        with torch.no_grad():
                            self.layers.eval()
                            validation_scores = torch.round(self.forward(data.validation.feature_matrix))
                        ndcg_result = evl.ndcg_at_k(validation_scores.numpy(), data.validation.label_vector, 0)
                        print('NDCG score at batch {}: {}'.format(b, ndcg_result))
                        if ndcg_result > ndcg_convergence:
                            converged = True
                            print('Convergence criteria (NDCG of {}) reached after {} epochs'.format(ndcg_convergence, e))
                            break
        if not converged:
            print('Done training for {} epochs'.format(num_epochs))

    def train_bgd2(self, data, lr=1e-3, batch_size=500, num_epochs=1, ndcg_convergence=0.95, eval_freq=1):
        self.layers.train()
        optimizer = torch.optim.Adam(self.layers.parameters(), lr=lr)
        num_queries = data.train.num_queries()
        converged = False
        for e in range(num_epochs):
            if converged:
                break
            random_query_order = np.arange(num_queries)
            np.random.shuffle(random_query_order)
            num_batches = int(np.ceil(num_queries/batch_size))
            offset = 0
            for b in range(num_batches):
                start = time()
                all_scores = self.forward(data.train.feature_matrix)
                end = time()
                print('Full trainset forward pass in {} seconds'.format(end - start))
                if b == 0:
                    start = time()
                    _ = self.forward(data.train.feature_matrix[0:1000])
                    end = time()
                    print('1000 trainset examples forward pass in {} seconds'.format(end - start))
                    start = time()
                    _ = self.forward(data.train.feature_matrix[0:500])
                    end = time()
                    print('500 trainset examples forward pass in {} seconds'.format(end-start))
                loss = 0.0
                for qid in tqdm(range(offset,batch_size+offset)):
                    s_i, e_i = data.train.query_range(random_query_order[qid])
                    query_scores = all_scores[s_i:e_i]
                    query_labels = data.train.query_labels(random_query_order[qid])
                    for i in range(len(query_scores)):
                        for j in range(len(query_scores)):
                            if i == j:
                                continue
                            loss += self.pair_cross_entropy(query_scores[i], query_scores[j], query_labels[i], query_labels[j])
                    if qid + 1 == num_queries:
                        break
                optimizer.zero_grad()
                loss /= batch_size
                loss.backward()
                optimizer.step()
                offset += batch_size

            if eval_freq != 0:
                if b % eval_freq == 0:
                    print('Average Loss: {} for batch {} of {} batches'.format(loss, b, num_batches))
                    with torch.no_grad():
                        self.layers.eval()
                        validation_scores = torch.round(self.forward(data.validation.feature_matrix))
                    ndcg_result = evl.ndcg_at_k(validation_scores.numpy(), data.validation.label_vector, 0)
                    print('NDCG score at batch {}: {}'.format(b, ndcg_result))
                    if ndcg_result > ndcg_convergence:
                        converged = True
                        print('Convergence criteria (NDCG of {}) reached after {} epochs'.format(ndcg_convergence, e))
                        break
        if not converged:
            print('Done training for {} epochs'.format(num_epochs))

    def train_bgd2_retain(self, data, lr=1e-3, batch_size=500, num_epochs=1, ndcg_convergence=0.95, eval_freq=1):
        self.layers.train()
        optimizer = torch.optim.Adam(self.layers.parameters(), lr=lr)
        num_queries = data.train.num_queries()
        converged = False
        for e in range(num_epochs):
            if converged:
                break
            random_query_order = np.arange(num_queries)
            np.random.shuffle(random_query_order)
            num_batches = int(np.ceil(num_queries/batch_size))
            offset = 0
            all_scores = self.forward(data.train.feature_matrix)
            for b in range(num_batches):
                loss = torch.tensor(0.0)
                for qid in tqdm(range(offset,batch_size+offset)):
                    s_i, e_i = data.train.query_range(random_query_order[qid])
                    query_scores = all_scores[s_i:e_i]
                    query_labels = data.train.query_labels(random_query_order[qid])
                    for i in range(len(query_scores)):
                        for j in range(len(query_scores)):
                            if i == j:
                                continue
                            loss += self.pair_cross_entropy(query_scores[i], query_scores[j], query_labels[i], query_labels[j])
                    if qid + 1 == num_queries:
                        break
                optimizer.zero_grad()
                loss /= batch_size
                if b < num_batches-1:
                    loss.backward(retain_graph=True)
                else:
                    loss.backward()
                optimizer.step()
                offset += batch_size

            if eval_freq != 0:
                if b % eval_freq == 0:
                    print('Average Loss: {} for batch {} of {} batches'.format(loss, b, num_batches))
                    with torch.no_grad():
                        self.layers.eval()
                        validation_scores = torch.round(self.forward(data.validation.feature_matrix))
                    ndcg_result = evl.ndcg_at_k(validation_scores.numpy(), data.validation.label_vector, 0)
                    print('NDCG score at batch {}: {}'.format(b, ndcg_result))
                    if ndcg_result > ndcg_convergence:
                        converged = True
                        print('Convergence criteria (NDCG of {}) reached after {} epochs'.format(ndcg_convergence, e))
                        break
        if not converged:
            print('Done training for {} epochs'.format(num_epochs))

    def train_sgd(self, data, lr=1e-3, batch_size=1, num_epochs=1, ndcg_convergence=0.95, eval_freq=1000):
        self.layers.train()
        optimizer = torch.optim.Adam(self.layers.parameters(), lr=lr)
        num_queries = data.train.num_queries()
        converged = False
        for e in range(num_epochs):
            if converged:
                break
            random_query_order = np.arange(num_queries)
            np.random.shuffle(random_query_order)
            for qid in tqdm(range(num_queries)):
                loss = 0.0
                s_i, e_i = data.train.query_range(random_query_order[qid])
                query_scores = self.forward(data.train.feature_matrix[s_i:e_i])
                query_labels = data.train.query_labels(random_query_order[qid])
                for i in range(len(query_scores)):
                    for j in range(len(query_scores)):
                        if i == j:
                            continue
                        loss += self.pair_cross_entropy(query_scores[i], query_scores[j], query_labels[i], query_labels[j])
                # to catch queries with only one document which result in no grad_fun for backprop
                if loss == 0:
                    continue
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

                if eval_freq != 0:
                    if qid % eval_freq == 0:
                        print('Average Loss epoch {}: {} after query {} of {} queries'.format(e, loss.item(), qid, num_queries))
                        with torch.no_grad():
                            self.layers.eval()
                            validation_scores = torch.round(self.forward(data.validation.feature_matrix))
                        ndcg_result = evl.ndcg_at_k(validation_scores.numpy(), data.validation.label_vector, 0)
                        print('NDCG score: {}'.format(ndcg_result))
                        if ndcg_result > ndcg_convergence:
                            converged = True
                            print('Convergence criteria (NDCG of {}) reached after {} epochs'.format(ndcg_convergence, e))
                            break
        if not converged:
            print('Done training for {} epochs'.format(num_epochs))

    def train_sgd_speed(self, data, lr=1e-3, batch_size=1, num_epochs=1, ndcg_convergence=0.95, eval_freq=0):
        self.layers.train()
        optimizer = torch.optim.Adam(self.layers.parameters(), lr=lr)
        num_queries = data.train.num_queries()
        converged = False
        for e in range(num_epochs):
            if converged:
                break
            random_query_order = np.arange(num_queries)
            np.random.shuffle(random_query_order)
            for qid in tqdm(range(num_queries)):
                s_i, e_i = data.train.query_range(random_query_order[qid])
                query_scores = self.forward(data.train.feature_matrix[s_i:e_i])
                query_labels = data.train.query_labels(random_query_order[qid])

                # to catch cases with less than two documents (as no loss can be computed if there is no document pair)
                if len(query_labels) < 2:
                    continue

                score_combs = list(zip(*combinations(query_scores, 2)))
                score_combs_i = torch.stack(score_combs[0]).squeeze()
                score_combs_j = torch.stack(score_combs[1]).squeeze()

                label_combs = np.array(list(combinations(query_labels, 2)))
                label_combs_i = torch.from_numpy(label_combs[:, 0])
                label_combs_j = torch.from_numpy(label_combs[:, 1])

                loss = self.pair_cross_entropy_vectorized(score_combs_i, score_combs_j,
                                                          label_combs_i, label_combs_j)

                optimizer.zero_grad()
                loss.backward()
                optimizer.step()

                if eval_freq != 0:
                    if qid % eval_freq == 0:
                        print('Average Loss epoch {}: {} after query {} of {} queries'.format(e, loss.item(), qid, num_queries))
                        with torch.no_grad():
                            self.layers.eval()
                            validation_scores = torch.round(self.forward(data.validation.feature_matrix))
                        ndcg_result = evl.ndcg_at_k(validation_scores.numpy(), data.validation.label_vector, 0)
                        print('NDCG score: {}'.format(ndcg_result))
                        if ndcg_result > ndcg_convergence:
                            converged = True
                            print('Convergence criteria (NDCG of {}) reached after {} epochs'.format(ndcg_convergence, e))
                            break
        if not converged:
            print('Done training for {} epochs'.format(num_epochs))

    def train_sgd_speed2(self, data, lr=1e-5, batch_size=1, num_epochs=1, ndcg_convergence=0.95, eval_freq=0):
        self.layers.train()
        optimizer = torch.optim.Adam(self.layers.parameters(), lr=lr)
        num_queries = data.train.num_queries()
        converged = False
        for e in range(num_epochs):
            if converged:
                break
            #random_query_order = np.arange(num_queries)
            #np.random.shuffle(random_query_order)
            all_scores = self.forward(data.train.feature_matrix)
            all_loss = 0
            for qid in tqdm(range(num_queries)):
                s_i, e_i = data.train.query_range(qid)#random_query_order[qid])
                query_scores = all_scores[s_i:e_i]
                query_labels = data.train.query_labels(qid)#random_query_order[qid])

                # to catch cases with less than two documents (as no loss can be computed if there is no document pair)
                if len(query_labels) < 2:
                    continue

                score_combs = list(zip(*combinations(query_scores, 2)))
                score_combs_i = torch.stack(score_combs[0]).squeeze()
                score_combs_j = torch.stack(score_combs[1]).squeeze()

                label_combs = np.array(list(combinations(query_labels, 2)))
                label_combs_i = torch.from_numpy(label_combs[:, 0])
                label_combs_j = torch.from_numpy(label_combs[:, 1])

                loss = self.pair_cross_entropy_vectorized(score_combs_i, score_combs_j,
                                                          label_combs_i, label_combs_j)

                all_loss += loss

                if eval_freq != 0:
                    if qid % eval_freq == 0:
                        print('Average Loss epoch {}: {} after query {} of {} queries'.format(e, loss.item(), qid, num_queries))
                        with torch.no_grad():
                            self.layers.eval()
                            validation_scores = torch.round(self.forward(data.validation.feature_matrix))
                        ndcg_result = evl.ndcg_at_k(validation_scores.numpy(), data.validation.label_vector, 0)
                        print('NDCG score: {}'.format(ndcg_result))
                        if ndcg_result > ndcg_convergence:
                            converged = True
                            print('Convergence criteria (NDCG of {}) reached after {} epochs'.format(ndcg_convergence, e))
                            break
            all_loss /= num_queries
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

        if not converged:
            print('Done training for {} epochs'.format(num_epochs))

    def train_gd(self, data, lr=1e-3, batch_size=1, num_epochs=1, ndcg_convergence=0.95, eval_freq=1):
        self.layers.train()
        optimizer = torch.optim.Adam(self.layers.parameters(), lr=lr)
        num_queries = data.train.num_queries()
        converged = False
        for e in range(num_epochs):
            if converged:
                break
            all_scores = self.forward(data.train.feature_matrix)
            loss = []
            for qid in tqdm(range(num_queries)):
                s_i, e_i = data.train.query_range(qid)
                query_scores = all_scores[s_i:e_i]
                query_labels = data.train.query_labels(qid)
                for i in range(len(query_scores)):
                    for j in range(len(query_scores)):
                        if i == j:
                            continue
                        loss.append(self.pair_cross_entropy(query_scores[i], query_scores[j], query_labels[i], query_labels[j]))

            optimizer.zero_grad()
            loss = torch.stack(loss, dim=0).sum(dim=0)
            loss /= num_queries
            loss.backward()
            optimizer.step()

            if eval_freq != 0:
                if e % eval_freq == 0:
                    print('Average Loss per query: {} in epoch {}'.format(loss, e))
                    with torch.no_grad():
                        self.layers.eval()
                        validation_scores = torch.round(self.forward(data.validation.feature_matrix))
                    ndcg_result = evl.ndcg_at_k(validation_scores.numpy(), data.validation.label_vector, 0)
                    print('NDCG score at epoch {}: {}'.format(e, ndcg_result))
                    if ndcg_result > ndcg_convergence:
                        converged = True
                        print('Convergence criteria (NDCG of {}) reached after {} epochs'.format(ndcg_convergence, e))
                        break
        if not converged:
            print('Done training for {} epochs'.format(num_epochs))

    def pair_cross_entropy(self, s_i, s_j, S_i, S_j):
        Sij = 1.0 if S_i > S_j else (-1.0 if S_i < S_j else 0.0)
        sig_diff = self.sigma * (s_i - s_j)
        return 0.5 * (1-Sij) * sig_diff + torch.log(1 + torch.exp(-sig_diff))

    def pair_cross_entropy_vectorized(self, s_i, s_j, S_i, S_j):
        S_diff = S_i - S_j
        Sij = np.where(S_diff > 0, 1.0, -1.0)
        Sij = torch.from_numpy(np.where(S_diff == 0, 0.0, Sij))
        sig_diff = self.sigma * (s_i - s_j)
        return torch.sum(0.5 * (1 - Sij) * sig_diff + torch.log(1 + torch.exp(-sig_diff)))

    def evaluate(self, data_fold, print_results=False):
        self.layers.eval()
        with torch.no_grad():
            validation_scores = torch.round(self.forward(data_fold.feature_matrix)).squeeze().numpy()
        results = evl.evaluate(data_fold, validation_scores, print_results=print_results)
        return results

    def save(self, path='./rank_net'):
        torch.save(self.state_dict(), path)

    def prepare_batches(self, data_fold, num_queries, batch_size):
        random_query_order = np.arange(num_queries)
        np.random.shuffle(random_query_order)
        batches = []
        #query_sizes = []
        num_batches = int(np.ceil(num_queries/batch_size))
        offset = 0
        for i in tqdm(range(num_batches)):
            step = batch_size if i < num_batches-1 else num_queries - i*batch_size
            batch_queries = random_query_order[offset:offset+step+1]
            features_batch = np.array([])
            labels_batch = np.array([])
            #query_sizes_batch = []
            for qid in batch_queries:
                features_qid = data_fold.query_feat(qid)
                labels_qid = data_fold.query_labels(qid)
                #query_sizes_batch.append((qid, len(labels_qid)))
                features_batch = np.vstack([features_batch, features_qid]) if features_batch.size else features_qid
                labels_batch = np.append(labels_batch, labels_qid) if labels_batch.size else labels_qid
            batches.append((features_batch,labels_batch))
            #query_sizes.append(query_sizes_batch)
            offset += batch_size
        return batches#, query_sizes

def r(g, g_max=4):
    return (2**g-1 / 2**g_max)

def err(ranking_labels):
    p = 1.0
    ERR = 0.0
    for r in range(len(ranking_labels)):
        R = r(ranking_labels[r])
        ERR += p * R/(r+1)
        p *= 1-R
    return ERR


if __name__ == "__main__":
    data = dataset.get_dataset().get_data_folds()[0]
    data.read_data()

    net2 = Rank_Net(data.num_features)
    start = time()
    net2.train_sgd_speed2(data, num_epochs=20)
    end = time()
    print('Finished training in {} minutes'.format((end-start)/60))
    net2.save(path='./rank_net'+str(net2.model_id)+'.weights')
    final_test_results = net2.evaluate(data.test,print_results=True)
    with open('eval'+str(net2.model_id), 'wb') as f:
        pickle.dump(final_test_results, f)

    # net = Rank_Net(data.num_features)
    # start = time()
    # net.train_bgd2_retain(data)
    # end = time()
    # print('Finished training in {} minutes'.format((end - start) / 60))
    # net.save(path='./rank_net' + str(net.model_id) + '.weights')
    # final_test_results = net.evaluate(data.test, print_results=True)
    # with open('eval' + str(net.model_id), 'wb') as f:
    #     pickle.dump(final_test_results, f)
