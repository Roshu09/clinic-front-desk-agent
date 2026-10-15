Model: `openai/gpt-oss-120b`

| conversation | turns | terminal_state | tokens | latency (ms) |
|---|---|---|---|---|
| adv_0001 | 2 | escalated | 1157 | 2485 |
| adv_0002 | 2 | booked | 1205 | 1896 |
| adv_0003 | 3 | escalated | 1010 | 1854 |
| adv_0004 | 2 | escalated | 1052 | 1116 |
| adv_0005 | 3 | booked | 1267 | 1801 |
| adv_0006 | 2 | abandoned | 1100 | 2801 |
| adv_0007 | 3 | abandoned | 1033 | 1126 |
| adv_0008 | 2 | escalated | 1068 | 2162 |
| cv_0001 | 3 | booked | 972 | 999 |
| cv_0002 | 3 | booked | 1184 | 1094 |
| cv_0003 | 3 | rescheduled | 1229 | 2296 |
| cv_0004 | 2 | cancelled | 1036 | 5122 |
| cv_0005 | 3 | abandoned | 1228 | 7983 |
| cv_0006 | 3 | booked | 1311 | 6760 |
| cv_0007 | 3 | escalated | 1272 | 5323 |
| cv_0008 | 3 | booked | 1229 | 5120 |
| cv_0009 | 3 | escalated | 1264 | 9214 |
| cv_0010 | 3 | escalated | 1176 | 6552 |
| cv_0011 | 3 | escalated | 1204 | 3993 |
| cv_0012 | 2 | booked | 1118 | 9012 |
| cv_0013 | 3 | abandoned | 859 | 2864 |
| cv_0014 | 3 | refused | 1244 | 5221 |
| cv_0015 | 3 | booked | 1245 | 8399 |

**Mean:** 1151 tokens, 4139 ms per conversation (median 2864 ms, max 9214 ms) over 23 conversations.

NLU mode seen: llm:openai/gpt-oss-120b + rules
