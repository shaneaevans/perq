=======
PSearch
=======

Welcome to PSearch

Introduction
============

PSearch is a python library for prospective or persistent search. It finds matching queries for a document. This is different to traditional, or retrospective search, which finds matching documents for a query.

This is often used in 'alerts' applications, where users are alerted to new documents matching their queries. It can also be useful for generating matches in batch processing.

Typical use:
 * Create an index of queries
 * Repeatedly query that index with documents to find matches

Installation
============

PSearch requires Python 3.11 or later.

Install the package in editable mode:

::

    python -m pip install -e .

Install LMDB support:

::

    python -m pip install -e .[lmdb]

Install test dependencies:

::

    python -m pip install -e .[test]

Install benchmark dependencies:

::

    python -m pip install -e .[benchmark]

Sample Usage
============

Create a store to hold the index
    >>> store = MemoryStore()

Add some queries to the store:
    >>> query1 = Query(1, [('information',), ('retrieval',)])
    >>> query2 = Query(2, [('text', 'data'), ('mining',)], filters=[('price', 100, 200)])
    >>> index([query1, query2], store)

Create a matcher:
    >>> matcher = QueryMatcher(store)

Match queries to documents:
    >>> doc = Document({'name': [['introduction', 'to', 'information', 'retrieval']]}, rangefilters={'price': [30.0]})
    >>> list(matcher.matches(doc))
    [1]

This example is explained in the sections that follow.

Details
=======

Storage
-------

The method of storing indexed queries is configurable. PSearch currently ships with 3 storage backends:

MemoryStore 
    Holds all data in memory. Data can optionally be read from or written to disk (uses pickle).

SQLiteStore
    Stores data in SQLite using WAL mode for a durable, portable on-disk index.

LMDBStore
    Stores data in LMDB for read-heavy workloads where embedded key-value performance matters.

Terms
-----

Terms are the *indexed units* in Information Retrieval. PSearch assumes documents and queries are already converted into terms, which are represented as a sequence of strings and makes no assumptions about the contents of these strings. In the example above, the document name "Introduction to Information Retrieval" is converted into the terms ``['introduction', 'to', 'information', 'retrieval']``. Although this could be achieved with ``str.lower().split()``, it is common to:
 * use more sophisticated tokenization (splitting the text into words, phrases or symbols).
 * stem words (e.g. converting "fishing", "fished", "fish", and "fisher" to the root word, "fish")
 * remove stop words ('and', 'the', 'of', etc.)
 * add extra words to support synonyms. For example, adding "IR" as a synonym for "Information Retrieval".
 * add prefixes to terms based on the field in which they occur to support searching by field of the document.
  
Usually the converting of text to terms is application specific. There are many python libraries that are useful, for example nltk_ has several good algorithms for tokenization and stemming and contains lists of stop words.

The process used for converting the query to terms must be compatible with the process used for converting documents.

.. _nltk: http://nltk.org

Queries
-------

Queries contain an ID, terms, filters and optional user defined fields. The query terms are specified as a sequence of sequences of terms. The terms in each nested sequence are combined with OR and the sequences themselves are combined with AND.

Filters can be used to match numeric ranges. They consist of a starting value and an optional end value that specify the range.

In our example above, the first query searches for "information AND retrieval" and the second query searches for "(text OR data) AND mining" and filters the results so that all documents have a price between 100 and 200.

Documents
---------

Documents consist of:

Text Search Terms
    A mapping from fields to a sequence of sequences of terms. This allows for typical multi-valued document fields found in many applications
Range Filters
    A mapping from fields to terms that can be used in range queries


Limitations
-----------

Queries are currently limited to 31 terms, excluding terms combined with OR. This limit can be changed internally. This is a common upper bound, at the time of writing, google limits searches to 32 words.

Testing
-------

Run the test suite with:

::

    pytest

Benchmarks
----------

Run the benchmark suite with:

::

    pytest benchmarks/test_benchmarks.py --benchmark-min-rounds=3

Measured results on a 2023 MacBook Pro with Apple M3 for the 10,000-query
synthetic workload in ``benchmarks/test_benchmarks.py``:

+-------------+------------------+--------------------+--------------------------+
| Backend     | Index queries/s  | Match docs/s       | Time for 10,000 matches  |
+=============+==================+====================+==========================+
| MemoryStore | ~173,000         | ~23,500            | ~0.43s                   |
+-------------+------------------+--------------------+--------------------------+
| SQLiteStore | ~40,500          | ~2,550             | ~3.93s                   |
+-------------+------------------+--------------------+--------------------------+
| LMDBStore   | ~9,920           | ~5,630             | ~1.78s                   |
+-------------+------------------+--------------------+--------------------------+

These numbers come from indexing 10,000 generated queries and matching 250
generated documents against an already-open store. They are useful for
backend comparison, not as universal capacity figures.
