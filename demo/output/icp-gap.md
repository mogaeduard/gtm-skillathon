# DECLARED ICP vs ACTUAL ICP

Left column: what your own public positioning says, read from the declared file. Right column: what the customers you actually closed show on their websites, fetched in this run. Nothing here is inferred from private data.

| Axis | You say | Your customers show | Verdict |
| --- | --- | --- | --- |
| Business line: saas_product | not named | 50% of customers | **blind spot** |
| Business line: martech | named (lead generation, sentiment) | 40% of customers | **match** |
| Business line: nonprofit_community | not named | 10% of customers | **minor** |
| Business line: ecommerce | named (e-commerce, product development) | 0% of customers | **overclaim** |
| Business line: ai_llm | named (ai, data feed) | 0% of customers | **overclaim** |
| Business line: real_estate | named (hospitality, real estate) | 0% of customers | **overclaim** |
| Hiring right now | not named | 60% of customers | **blind spot** |
| Romania | not named | 0% of customers | **match** |
| Site language | not stated as a filter | majority en | **blind spot** |
| Company size | enterprise, small team, solo, startup | modal band 201-1000 | **mismatch** |

## Blind spots

- 50% of your customers are saas product, and your public positioning never names that segment.
- 60% of your customers are actively hiring. That is a timing signal you are not using anywhere in your messaging.
- You position at the two ends (enterprise, small team, solo) but your customers cluster at 201-1000. The middle is where you actually win.

## Where you are talking to the wrong room

- You market to ecommerce. No customer in this list was classified that way from its own homepage, which is either a segment you have not closed or a segment whose sites do not say so.
- You market to ai llm. No customer in this list was classified that way from its own homepage, which is either a segment you have not closed or a segment whose sites do not say so.
- You market to real estate. No customer in this list was classified that way from its own homepage, which is either a segment you have not closed or a segment whose sites do not say so.

## How to read this

- A **blind spot** is a pattern strong enough to target that you never mention. It is usually the cheapest thing to fix: it costs a line of copy, not a strategy.
- An **overclaim** is a segment you market to and have not closed. Either the message is wrong or the segment is.
- Classification reads each customer's own homepage. A customer whose site does not say what it sells will not be counted in its real segment, so read an overclaim as a question to check, not a verdict.
- This compares text to evidence, not opinion to opinion. Every number on the right comes from a page in `evidence.json` with its retrieval time.
- ICP confidence for this run: medium, derived from 10 customers with usable evidence.
