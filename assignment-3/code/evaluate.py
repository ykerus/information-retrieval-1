import dataset
import numpy as np


def err(labels, k=0, query_dcg=None):
    p = 1
    err = 0
    g_max = max(labels)
    for r in range(len(labels)):
        g = labels[r]
        R = (2 ** g - 1) / (2 ** g_max)
        err += p * R / (r+1)
        p *= 1 - R
    return err


def dcg_at_k(sorted_labels, k):
  if k > 0:
    k = min(sorted_labels.shape[0], k)
  else:
    k = sorted_labels.shape[0]
  denom = 1./np.log2(np.arange(k)+2.)
  nom = 2**sorted_labels-1.
  dcg = np.sum(nom[:k]*denom)
  return dcg


def ndcg_at_k(sorted_labels, ideal_labels, k):
  return dcg_at_k(sorted_labels, k) / dcg_at_k(ideal_labels, k)

def big_R(g, g_max=4):
  return (2 ** g - 1) / (2 ** g_max)

def err_rank_net(ranking_labels):
  p = 1.0
  ERR = 0.0
  for r in range(len(ranking_labels)):
    R = big_R(ranking_labels[r],g_max=max(ranking_labels))
    ERR += p * R / (r + 1)
    p *= 1 - R
  return ERR

def ndcg_speed(sorted_labels, k, query_dcg_at_k):
  return dcg_at_k(sorted_labels, k) / (query_dcg_at_k+1e-8)


def evaluate_query(data_split, qid, all_scores):
  s_i, e_i = data_split.doclist_ranges[qid:qid+2]
  q_scores = all_scores[s_i:e_i]
  q_labels = data_split.query_labels(qid)
  return evaluate_labels_scores(q_labels, q_scores)

def evaluate_labels_scores(labels, scores):
  n_docs = labels.shape[0]

  random_i = np.random.permutation(
               np.arange(scores.shape[0])
             )
  labels = labels[random_i]
  scores = scores[random_i]

  sort_ind = np.argsort(scores)[::-1]
  sorted_labels = labels[sort_ind]
  ideal_labels = np.sort(labels)[::-1]

  bin_labels = np.greater(sorted_labels, 2)
  bin_ideal_labels = np.greater(ideal_labels, 2)

  rel_i = np.arange(1,len(sorted_labels)+1)[bin_labels]

  total_labels = float(np.sum(bin_labels))
  assert total_labels > 0 or np.any(np.greater(labels, 0))
  if total_labels > 0:
    result = {
      'relevant rank': list(rel_i),
      'relevant rank per query': np.sum(rel_i),
      'arr': np.sum(rel_i)/len(sorted_labels),
      'err_rank_net': err_rank_net(sorted_labels),
      'precision@01': np.sum(bin_labels[:1])/1.,
      'precision@03': np.sum(bin_labels[:3])/3.,
      'precision@05': np.sum(bin_labels[:5])/5.,
      'precision@10': np.sum(bin_labels[:10])/10.,
      'precision@20': np.sum(bin_labels[:20])/20.,
      'recall@01': np.sum(bin_labels[:1])/total_labels,
      'recall@03': np.sum(bin_labels[:3])/total_labels,
      'recall@05': np.sum(bin_labels[:5])/total_labels,
      'recall@10': np.sum(bin_labels[:10])/total_labels,
      'recall@20': np.sum(bin_labels[:20])/total_labels,
      'dcg': dcg_at_k(sorted_labels, 0),
      'dcg@03': dcg_at_k(sorted_labels, 3),
      'dcg@05': dcg_at_k(sorted_labels, 5),
      'dcg@10': dcg_at_k(sorted_labels, 10),
      'dcg@20': dcg_at_k(sorted_labels, 20),
      'ndcg': ndcg_at_k(sorted_labels, ideal_labels, 0),
      'ndcg@03': ndcg_at_k(sorted_labels, ideal_labels, 3),
      'ndcg@05': ndcg_at_k(sorted_labels, ideal_labels, 5),
      'ndcg@10': ndcg_at_k(sorted_labels, ideal_labels, 10),
      'ndcg@20': ndcg_at_k(sorted_labels, ideal_labels, 20),
      'err': err(sorted_labels, 0)
    }
  else:
    result = {
      'dcg': dcg_at_k(sorted_labels, 0),
      'dcg@03': dcg_at_k(sorted_labels, 3),
      'dcg@05': dcg_at_k(sorted_labels, 5),
      'dcg@10': dcg_at_k(sorted_labels, 10),
      'dcg@20': dcg_at_k(sorted_labels, 20),
      'ndcg': ndcg_at_k(sorted_labels, ideal_labels, 0),
      'err_rank_net': err_rank_net(sorted_labels),
      'ndcg@03': ndcg_at_k(sorted_labels, ideal_labels, 3),
      'ndcg@05': ndcg_at_k(sorted_labels, ideal_labels, 5),
      'ndcg@10': ndcg_at_k(sorted_labels, ideal_labels, 10),
      'ndcg@20': ndcg_at_k(sorted_labels, ideal_labels, 20),
      'err': err(sorted_labels, 0)
    }
  return result

def included(qid, data_split):
  return np.any(np.greater(data_split.query_labels(qid), 0))

def add_to_results(results, cur_results):
  for k, v in cur_results.items():
    if not (k in results):
      results[k] = []
    if type(v) == list:
      results[k].extend(v)
    else:
      results[k].append(v)

def evaluate(data_split, all_scores, print_results=False):
  results = {}
  for qid in np.arange(data_split.num_queries()):
    if included(qid, data_split):
      add_to_results(results, evaluate_query(data_split, qid, all_scores))

  if print_results:
    print('"metric": "mean" ("standard deviation")')
  mean_results = {}
  for k in sorted(results.keys()):
    v = results[k]
    mean_v = np.mean(v)
    std_v = np.std(v)
    mean_results[k] = (mean_v, std_v)
    if print_results:
      print('%s: %0.04f (%0.05f)' % (k, mean_v, std_v))
  return mean_results
