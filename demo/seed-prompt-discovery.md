# Seed prompt, discovery mode (no prospect list)

Paste into Codex from the repo root. Use this one when the question is
"who should we even be talking to", i.e. there is no prospect list yet.

```
$icp-validator Use demo/input/customers.csv as our customers and demo/input/offer.md as
the offer. We have no prospect list. Source the prospects from the public sponsor page
https://www.devtalks.ro/ , print the ranked fit table as soon as the collector prints it,
then draft the top three openers. Full reports go to out/.
```

The collector fetches that one page, keeps the outbound company links, drops directories,
social networks, press and job boards, writes `out/discovered.csv` plus
`out/discovery.json` with the source URL and retrieval time, and scores what it found
against the ICP derived from our own customers. Same 75 second budget: discovery is one
extra HTTP request.
