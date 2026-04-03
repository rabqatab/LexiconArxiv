# LLM Reasoning Reliability & Logical Consistency
## A Research Landscape Report

*Generated from LexiconArxiv corpus (152,769 papers indexed)*
*50 papers retrieved | Query time: 52741ms*

---

## 1. Definition & Scope

**LLM Reasoning Reliability** refers to the ability of large language models to produce logically sound, consistent, and verifiable reasoning chains. It encompasses:

- **Logical Consistency**: Whether an LLM's outputs are free from self-contradictions -- both within a single response and across multiple prompts on the same topic
- **Deductive Competence**: The ability to correctly apply formal logical rules (modus ponens, syllogisms, first-order logic) to reach valid conclusions
- **Chain-of-Thought Reliability**: Whether intermediate reasoning steps in a CoT chain are individually valid and jointly support the final conclusion
- **Reasoning Stability**: Consistency of answers when the same logical problem is rephrased, reordered, or presented with irrelevant distractors

The field has evolved from asking *Can LLMs reason?* (2022-2023) to *How do we make their reasoning reliable?* (2024-2026), driven by the deployment of LLMs in high-stakes applications where logical errors have real consequences.

## 2. Recent Trends

### Keyword Growth

| Keyword | Growth | Timeline |
|---------|--------|----------|
| graph | 99x | 2020:1 > 2025:3 |
| decision-making | 99x | 2025:2 |
| benchmarking | 99x | 2025:2 |
| mathematics | 99x | 2025:1 > 2026:1 |
| benchmark | 7x | 2021:1 > 2024:1 > 2025:6 > 2026:1 |
| llms | 5x | 2023:1 > 2024:2 > 2025:12 > 2026:2 |
| llm | 4x | 2024:3 > 2025:7 > 2026:4 |
| dataset | 2x | 2021:1 > 2024:1 > 2025:1 > 2026:1 |
| reasoning | 2x | 2020:1 > 2023:1 > 2024:1 > 2025:3 |

### Key Trends

1. **Neuro-symbolic integration** (2025-2026): Combining neural LLMs with symbolic logic engines (SAT solvers, theorem provers) for formal verification of reasoning chains
2. **Step-wise logical supervision** (2025-2026): Training reward models that evaluate each reasoning step, not just the final answer
3. **Consistency benchmarks proliferation** (2024-2026): Shift from general reasoning benchmarks to those specifically measuring logical consistency
4. **Test-time reasoning scaling** (2025-2026): Methods like logic unit alignment and confidence-enhanced reasoning that improve reliability at inference time
5. **Internal mechanism analysis** (2025): Understanding why LLMs fail logically by examining attention patterns and heuristic-to-rational dynamics

### Venue Distribution

| Venue | Papers |
|-------|--------|
| Proceedings of the 2024 Conference on Empirical Methods in N | 5 |
| ICLR 2025 Poster | 4 |
| Proceedings of the AAAI Conference on Artificial Intelligenc | 4 |
| ICLR 2026 Poster | 4 |
| Proceedings of the 63rd Annual Meeting of the Association fo | 4 |
| NeurIPS 2025 poster | 4 |
| Proceedings of the 62nd Annual Meeting of the Association fo | 3 |
| Findings of the Association for Computational Linguistics: E | 3 |
| Proceedings of the 2024 Conference of the North American Cha | 3 |
| Proceedings of the 63rd Annual Meeting of the Association fo | 2 |

## 3. Paper Catalog

### 1. Logically Consistent Language Models via Neuro-Symbolic Integration

**Authors:** Diego Calanzone, Stefano Teso, Antonio Vergari
**Venue:** ICLR 2025 Poster (2025)
**Combined Score:** 0.75 (relevance: 1.00, notable: 0.37)
**Keywords:** reasoning, fine-tuning, LLM
**Abstract:** Current large language models (LLMs) are far from reliable: they are prone to generate non-factual information and, more crucially, to contradict themselves when prompted to reason about relations between real entities of the world. These problems are currently addressed with large scale fine-tuning...
**Links:** [PDF](https://openreview.net/pdf/a0e20167f4ff212dd87a42eee1b010ac878115fa.pdf) | [Code](https://github.com/ddidacus/loco-llm.)

### 2. LLM-DR: A Novel LLM-Aided Diffusion Model for Rule Generation on Temporal Knowledge Graphs

**Authors:** Kai Chen, Xin Song, Ye Wang et al.
**Venue:** Proceedings of the AAAI Conference on Artificial Intelligence (2025)
**Combined Score:** 0.59 (relevance: 0.54, notable: 0.67)
**Citations:** 1
**Keywords:** rule generation, LLM-DR, LLM
**Abstract:** Among various temporal knowledge graph (TKG) extrapolation methods, rule-based approaches stand out for their explicit rules and transparent reasoning paths. However, the vast search space for rule extraction poses a challenge in identifying high-quality logic rules. To navigate this challenge, we e...
**Links:** [PDF](https://ojs.aaai.org/index.php/AAAI/article/download/33249/35404)

### 3. LogiConBench: Benchmarking Logical Consistencies of LLMs

**Authors:** Zheng CHEN, Chuan Zhou, Fengxiang Cheng et al.
**Venue:** ICLR 2026 Poster (2026)
**Combined Score:** 0.59 (relevance: 0.71, notable: 0.40)
**Keywords:** LogiConBench, benchmark, dataset
**Abstract:** Logical consistency, the requirement that statements remain non-contradictory under logical rules, is fundamental for trustworthy reasoning, yet current LLMs often fail to maintain it even on simple inference tasks. Existing benchmarks for LLM logical consistency are not scalable, not diverse, and n...
**Links:** [PDF](https://openreview.net/pdf/ea332ba56ca3db700d0be2143b13a2aa38d2407b.pdf)

### 4. Logical Consistency of Large Language Models in Fact-Checking

**Authors:** Bishwamittra Ghosh, Sarah Hasan, Naheed Anjum Arafat et al.
**Venue:** ICLR 2025 Poster (2025)
**Combined Score:** 0.57 (relevance: 0.71, notable: 0.37)
**Keywords:** fact-checking, LLMs, benchmark, graph
**Abstract:** In recent years, large language models (LLMs) have demonstrated significant success in performing varied natural language tasks such as language translation, question-answering, summarizing, fact-checking, etc. Despite LLMs’ impressive ability to generate human-like texts, LLMs are infamous for thei...
**Links:** [PDF](https://openreview.net/pdf/df170ff11001dd99382ac48eab4c4c520bef7205.pdf)

### 5. Content-free Logical Modification of Large Language Model by Disentangling and Modifying Logic Representation

**Authors:** Wu Xin, Yuqi Bu, Yifei Chen et al.
**Venue:** Proceedings of the AAAI Conference on Artificial Intelligence (2025)
**Combined Score:** 0.54 (relevance: 0.66, notable: 0.37)
**Keywords:** LCF, LLMs
**Abstract:** Despite extensive training on diverse datasets and alignment with human values, large language models (LLMs) can still generate fallacious outputs. Additionally, the validity of LLM's outputs varies significantly depending on the content. It is crucial to ensure LLMs' logical consistency across diff...
**Links:** [PDF](https://ojs.aaai.org/index.php/AAAI/article/download/34740/36895) | [Code](https://github.com/wulidongdong/LCF)

### 6. Divide and Translate: Compositional First-Order Logic Translation and Verification for Complex Logical Reasoning

**Authors:** Hyun Ryu, Gyeongman Kim, Hyemin S. Lee et al.
**Venue:** ICLR 2025 Poster (2025)
**Combined Score:** 0.54 (relevance: 0.66, notable: 0.37)
**Keywords:** LLM, SAT solver, CLOVER
**Abstract:** Complex logical reasoning tasks require a long sequence of reasoning, which a large language model (LLM) with chain-of-thought prompting still falls short. To alleviate this issue, neurosymbolic approaches incorporate a symbolic solver. Specifically, an LLM only translates a natural language problem...
**Links:** [PDF](https://openreview.net/pdf/61bea6fe0297610c7dbfd47ab97cdc6e7d21c02f.pdf) | [Code](https://github.com/Hyun-Ryu/clover)

### 7. Verifiable, Debuggable, and Repairable Commonsense Logical Reasoning via LLM-based Theory Resolution

**Authors:** Armin Toroghi, Willis Guo, Ali Pesaranghader et al.
**Venue:** Proceedings of the 2024 Conference on Empirical Methods in Natural Language Processing (2024)
**Combined Score:** 0.49 (relevance: 0.58, notable: 0.34)
**Keywords:** debugging, repair, LLM-TRes, LLM
**Abstract:** Recent advances in Large Language Models (LLM) have led to substantial interest in their application to commonsense reasoning tasks. Despite their potential, LLMs are susceptible to reasoning errors and hallucinations that may be harmful in use cases where accurate reasoning is critical. This challe...
**Links:** [PDF](https://aclanthology.org/2024.emnlp-main.379.pdf)

### 8. LogicBench: Towards Systematic Evaluation of Logical Reasoning Ability of Large Language Models

**Authors:** Mihir Parmar, Nisarg Patel, Neeraj Varshney et al.
**Venue:** Proceedings of the 62nd Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers) (2024)
**Combined Score:** 0.45 (relevance: 0.53, notable: 0.34)
**Keywords:** GPT-4, ChatGPT, Gemini, Llama-2, Mistral
**Abstract:** Recently developed large language models (LLMs) have been shown to perform remarkably well on a wide range of language understanding tasks. But, can they really “reason” over the natural language? This question has been receiving significant research attention and many reasoning skills such as commo...
**Links:** [PDF](https://aclanthology.org/2024.acl-long.739.pdf) | [Code](https://github.com/mihir3009/logicbench)

### 9. Logical forms complement probability in understanding language model (and human) performance

**Authors:** Yixuan Wang, Freda Shi
**Venue:** Proceedings of the 63rd Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers) (2025)
**Combined Score:** 0.45 (relevance: 0.51, notable: 0.37)
**Keywords:** modal logic, LLMs, dataset
**Abstract:** With the increasing interest in using large language models (LLMs) for planning in natural language, understanding their behaviors becomes an important research question. This work conducts a systematic investigation of LLMs’ ability to perform logical reasoning in natural language. We introduce a c...
**Links:** [PDF](https://aclanthology.org/2025.acl-long.824.pdf)

### 10. ChainEdit: Propagating Ripple Effects in LLM Knowledge Editing through Logical Rule-Guided Chains

**Authors:** Zilu Dong, Xiangqing Shen, Zinong Yang et al.
**Venue:** Proceedings of the 63rd Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers) (2025)
**Combined Score:** 0.41 (relevance: 0.44, notable: 0.37)
**Keywords:** ChainEdit, LLM, graph
**Abstract:** Current knowledge editing methods for large language models (LLMs) struggle to maintain logical consistency when propagating ripple effects to associated facts. We propose ChainEdit, a framework that synergizes knowledge graph-derived logical rules with LLM logical reasoning capabilities to enable s...
**Links:** [PDF](https://aclanthology.org/2025.acl-long.665.pdf) | [Code](https://github.com/NUSTM/ChainEdit.)

### 11. A Chain-of-Thought Is as Strong as Its Weakest Link: A Benchmark for Verifiers of Reasoning Chains

**Authors:** Alon Jacovi, Yonatan Bitton, Bernd Bohnet et al.
**Venue:** Proceedings of the 62nd Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers) (2024)
**Combined Score:** 0.40 (relevance: 0.44, notable: 0.34)
**Keywords:** REVEAL, benchmark, dataset
**Abstract:** Prompting language models to provide step-by-step answers (e.g., “Chain-of-Thought”) is the prominent approach for complex reasoning tasks, where more accurate reasoning chains typically improve downstream task performance. Recent literature discusses automatic methods to verify reasoning to evaluat...
**Links:** [PDF](https://aclanthology.org/2024.acl-long.254.pdf)

### 12. LogicReward: Incentivizing LLM Reasoning via Step-Wise Logical Supervision

**Authors:** Jundong Xu, Hao Fei, Huichi Zhou et al.
**Venue:** ICLR 2026 Poster (2026)
**Combined Score:** 0.39 (relevance: 0.38, notable: 0.40)
**Keywords:** theorem prover, reward system, LogicReward
**Abstract:** Although LLMs exhibit strong reasoning capabilities, existing training methods largely depend on outcome-based feedback, which can produce correct answers with flawed reasoning.
Prior work introduces supervision on intermediate steps but still lacks guarantees of logical soundness, which is crucial ...
**Links:** [PDF](https://openreview.net/pdf/13648e17108802fa1381d5f81f48a8cc9e120bac.pdf) | [Code](https://github.com/Aiden0526/Logic-Reward)

### 13. LogicAsker: Evaluating and Improving the Logical Reasoning Ability of Large Language Models

**Authors:** Yuxuan Wan, Wenxuan Wang, Yiliu Yang et al.
**Venue:** Proceedings of the 2024 Conference on Empirical Methods in Natural Language Processing (2024)
**Combined Score:** 0.38 (relevance: 0.41, notable: 0.34)
**Keywords:** predicate logic, fine-tuning, ChatGPT, GPT-4, GPT-4o
**Abstract:** We introduce LogicAsker, a novel approach for evaluating and enhancing the logical reasoning capabilities of large language models (LLMs) such as ChatGPT and GPT-4. Despite LLMs’ prowess in tasks like writing assistance, code generation, and machine translation, assessing their ability to reason has...
**Links:** [PDF](https://aclanthology.org/2024.emnlp-main.128.pdf) | [Code](https://github.com/yxwan123/logicasker)

### 14. CER: Confidence Enhanced Reasoning in LLMs

**Authors:** Ali Razghandi, Seyed Mohammad Hadi Hosseini, Mahdieh Soleymani Baghshah
**Venue:** Proceedings of the 63rd Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers) (2025)
**Combined Score:** 0.35 (relevance: 0.33, notable: 0.37)
**Keywords:** LLMs
**Abstract:** Ensuring the reliability of Large Language Models (LLMs) in complex reasoning tasks remains a formidable challenge, particularly in scenarios that demand precise mathematical calculations and knowledge-intensive open-domain generation. In this work, we introduce an uncertainty-aware framework design...
**Links:** [PDF](https://aclanthology.org/2025.acl-long.390.pdf) | [Code](https://github.com/sharif-ml-lab/CER)

### 15. Self-contradictory reasoning evaluation and detection

**Authors:** Ziyi Liu, Soumya Sanyal, Isabelle Lee et al.
**Venue:** Findings of the Association for Computational Linguistics: EMNLP 2024 (2024)
**Combined Score:** 0.33 (relevance: 0.36, notable: 0.28)
**Keywords:** GPT-4
**Abstract:** In a plethora of recent work, large language models (LLMs) demonstrated impressive reasoning ability, but many proposed downstream reasoning tasks only focus on performance-wise evaluation. Two fundamental questions persist: 1) how consistent is the reasoning, and 2) can models detect unreliable rea...
**Links:** [PDF](https://aclanthology.org/2024.findings-emnlp.213.pdf) | [Code](https://github.com/uscnlp-lime/Self-Contradictory)

### 16. Think Again! The Effect of Test-Time Compute on Preferences, Opinions, and Beliefs of Large Language Models

**Authors:** George Kour, Itay Nakash, Michal Shmueli-Scheuer et al.
**Venue:** Proceedings of the 63rd Annual Meeting of the Association for Computational Linguistics (Volume 6: Industry Track) (2025)
**Combined Score:** 0.31 (relevance: 0.26, notable: 0.37)
**Keywords:** LLMs, AI ethics, ethical domains, POBs, benchmark
**Abstract:** As Large Language Models (LLMs) become deeply integrated into human life and increasingly influence decision-making, it’s crucial to evaluate whether and to what extent they exhibit subjective preferences, opinions, and beliefs. These tendencies may stem from biases within the models, which may shap...
**Links:** [PDF](https://aclanthology.org/2025.acl-industry.45.pdf)

### 17. ProofTeller: Exposing recency bias in LLM reasoning and its side effects on communication

**Authors:** Mayank Jobanputra, Alisa Kovtunova, Brisca Balthes et al.
**Venue:** Proceedings of the 14th International Joint Conference on Natural Language Processing and the 4th Conference of the Asia-Pacific Chapter of the Association for Computational Linguistics (2025)
**Combined Score:** 0.28 (relevance: 0.27, notable: 0.31)
**Keywords:** human study, bias analysis, LLM, Biology, Drones
**Abstract:** Large language models (LLMs) are increasingly applied in domains that demand reliable and interpretable reasoning. While formal methods can generate provably correct proofs, these proofs are often inaccessible to non-expert users. This raises a natural question: can LLMs, when given a verified proof...
**Links:** [PDF](https://aclanthology.org/2025.ijcnlp-long.80.pdf) | [Code](https://github.com/mayankjobanputra/ProofTeller)

### 18. Dependency Matters: Enhancing LLM Reasoning with Explicit Knowledge Grounding

**Authors:** Xiangyu Wen, Min Li, Junhua Huang et al.
**Venue:** NeurIPS 2025 poster (2025)
**Combined Score:** 0.28 (relevance: 0.22, notable: 0.37)
**Keywords:** reasoning, GRiD, StrategyQA, CommonsenseQA, GPQA
**Abstract:** Large language models (LLMs) often produce reasoning steps that are superficially coherent yet internally inconsistent, leading to unreliable outputs. Since such failures typically arise from implicit or poorly-grounded knowledge, we introduce \emph{Grounded Reasoning in Dependency (GRiD)}, a novel ...
**Links:** [PDF](https://openreview.net/pdf/88669d564fe12a96458ad3ff7025be1f74506a21.pdf) | [Code](https://github.com/cure-lab/GRiD)

### 19. LLM-based Typed Hyperresolution for Commonsense Reasoning with Knowledge Bases

**Authors:** Armin Toroghi, Ali Pesaranghader, Tanmana Sadhu et al.
**Venue:** ICLR 2025 Poster (2025)
**Combined Score:** 0.28 (relevance: 0.22, notable: 0.37)
**Keywords:** Hyperresolution, Typed inference, LLM-TH, BART
**Abstract:** Large language models (LLM) are being increasingly applied to tasks requiring commonsense reasoning. Despite their outstanding potential, the reasoning process of LLMs is prone to errors and hallucinations that hinder their applicability, especially in high-stakes scenarios. Several works have attem...
**Links:** [PDF](https://openreview.net/pdf/6a2a2e728fee43e58cdbc8b3f5e9416484e88bd3.pdf) | [Code](https://github.com/atoroghi/LLM-TH)

### 20. Quantifying Logical Consistency in Transformers via Query-Key Alignment

**Authors:** Eduard Tulchinskii, Laida Kushnareva, Anastasia Voznyuk et al.
**Venue:** Proceedings of the 2025 Conference on Empirical Methods in Natural Language Processing (2025)
**Combined Score:** 0.28 (relevance: 0.22, notable: 0.37)
**Keywords:** QK-score, Transformers, LLMs, ProntoQA-OOD, PARARULE-Plus
**Abstract:** Large language models (LLMs) excel at many NLP tasks, yet their multi-step logical reasoning remains unreliable. Existing solutions such as Chain-of-Thought prompting generate intermediate steps but provide no internal check of their logical coherence. In this paper, we use the “QK-score”, a lightwe...
**Links:** [PDF](https://aclanthology.org/2025.emnlp-main.1785.pdf)

### 21. Aligning with Logic: Measuring, Evaluating and Improving Logical Preference Consistency in Large Language Models

**Authors:** Yinhong Liu, Zhijiang Guo, Tianya Liang et al.
**Venue:** ICML 2025 spotlightposter (2025)
**Combined Score:** 0.28 (relevance: 0.21, notable: 0.37)
**Keywords:** decision-making, evaluating LLMs, transitivity, commutativity, REPAIR
**Abstract:** Large Language Models (LLMs) are expected to be predictable and trustworthy to support reliable decision-making systems. Yet current LLMs often show inconsistencies in their judgments. In this work, we examine \textit{logical preference consistency} as a foundational requirement for building more de...
**Links:** [PDF](https://openreview.net/pdf/22e5bb6d6cc2c3f8feb775d0bd727272557ac1b3.pdf) | [Code](https://github.com/williamLyh/REPAIR)

### 22. Reasoning-as-Logic-Units: Scaling Test-Time Reasoning in Large Language Models Through Logic Unit Alignment

**Authors:** Cheryl Li, Tianyuan Xu, Steven Y. Guo
**Venue:** ICML 2025 poster (2025)
**Combined Score:** 0.27 (relevance: 0.21, notable: 0.37)
**Keywords:** RaLU, static analysis, GSM8K, MATH, HumanEval+ 
**Abstract:** Chain-of-Thought (CoT) prompting has shown promise in enhancing the reasoning capabilities of large language models (LLMs) by generating natural language (NL) rationales that lead to the final answer. However, it struggles with numerical computation, which has somehow led to the development of progr...
**Links:** [PDF](https://openreview.net/pdf/6aa74fc0e561c227106221047a601564fa021aef.pdf) | [Code](https://github.com/DeepAccept/RaLU.)

### 23. First Heuristic Then Rational: Dynamic Use of Heuristics in Language Model Reasoning

**Authors:** Yoichi Aoki, Keito Kudo, Tatsuki Kuribayashi et al.
**Venue:** Proceedings of the 2024 Conference on Empirical Methods in Natural Language Processing (2024)
**Combined Score:** 0.26 (relevance: 0.21, notable: 0.34)
**Keywords:** lexical overlap, Language Models
**Abstract:** Explicit multi-step reasoning, such as chain-of-thought, is widely adopted in the community to explore the better performance of language models (LMs). We report on the systematic strategy that LMs use in this process.Our controlled experiments reveal that LMs rely more heavily on heuristics, such a...
**Links:** [PDF](https://aclanthology.org/2024.emnlp-main.789.pdf) | [Code](https://github.com/ao1neko/Heuristic-and-Rational-Reasoning)

### 24. DivLogicEval: A Framework for Benchmarking Logical Reasoning Evaluation in Large Language Models

**Authors:** Tsz Ting Chung, Lemao Liu, Mo Yu et al.
**Venue:** Findings of the Association for Computational Linguistics: EMNLP 2025 (2025)
**Combined Score:** 0.26 (relevance: 0.23, notable: 0.31)
**Keywords:** benchmarking, LLMs, DivLogicEval, benchmark
**Abstract:** Logic reasoning in natural language has been recognized as an important measure of human intelligence for Large Language Models (LLMs). Popular benchmarks may entangle multiple reasoning skills and thus provide unfaithful evaluations on the logic reasoning skill. Meanwhile, existing logic reasoning ...
**Links:** [PDF](https://aclanthology.org/2025.findings-emnlp.47.pdf)

### 25. FACT: Mitigating Inconsistent Hallucinations in LLMs via Fact-Driven Alternating Code-Text Training

**Authors:** Xinxin You, Qixin Sun, Chenwei Yan et al.
**Venue:** NeurIPS 2025 poster (2025)
**Combined Score:** 0.26 (relevance: 0.19, notable: 0.37)
**Keywords:** FACT, LLMs, AI reliability, code
**Abstract:** Inconsistent hallucinations remain a major challenge for large language models (LLMs), undermining the accuracy and reliability of fact-based reasoning in real-world applications. Existing approaches often rely on task-specific training or adaptation, such as hand-crafted synthetic datasets for doma...
**Links:** [PDF](https://openreview.net/pdf/8f06a63c8a49d0e18846db034cd1bfcf042c535e.pdf)

### 26. Deep Hidden Cognition Facilitates Reliable Chain-of-Thought Reasoning

**Authors:** Zijun Chen, Wei Hu, Richang Hong
**Venue:** Proceedings of the AAAI Conference on Artificial Intelligence (2026)
**Combined Score:** 0.26 (relevance: 0.16, notable: 0.40)
**Keywords:** CoT, LLMs, LLM, MLLMs, MLLM
**Abstract:** Chain of Thought (CoT) reasoning has demonstrated remarkable deep reasoning capabilities in both large language models (LLMs) and multimodal large language models (MLLMs). However, its reliability is often undermined by the accumulation of errors in intermediate steps. This paper proposes a novel ap...
**Links:** [PDF](https://ojs.aaai.org/index.php/AAAI/article/download/41061/45022)

### 27. Conceptual Diagnostics for Knowledge Graphs and Large Language Models

**Authors:** Rosario Uceda Sosa, Maria Chang, Karthikeyan Natesan Ramamurthy et al.
**Venue:** Proceedings of the 63rd Annual Meeting of the Association for Computational Linguistics (Volume 6: Industry Track) (2025)
**Combined Score:** 0.25 (relevance: 0.17, notable: 0.37)
**Keywords:** probing, LLMs, benchmark
**Abstract:** Industrial applications pose heightened requirements for consistency and reliability of large language models (LLMs). While LLMs are being tested with increasingly complex reasoning tasks, we argue that much can be learned via diagnostic tools that probe a fundamentally basic type of reasoning: conc...
**Links:** [PDF](https://aclanthology.org/2025.acl-industry.37.pdf)

### 28. Reasoning Models Sometimes Output Illegible Chains of Thought

**Authors:** Arun Jose
**Venue:** NeurIPS 2025 poster (2025)
**Combined Score:** 0.24 (relevance: 0.15, notable: 0.37)
**Keywords:** R1, R1-Zero, QwQ, Claude, AI safety
**Abstract:** Language models trained via outcome-based reinforcement learning (RL) to reason using chain-of-thought (CoT) have shown remarkable performance. Monitoring such a model's CoT may allow us to understand its intentions and detect potential malicious behavior. However, to be effective, this requires tha...
**Links:** [PDF](https://openreview.net/pdf/05e549afc051441256cf30951d01249a053c7ab0.pdf)

### 29. Evaluating the Deductive Competence of Large Language Models

**Authors:** S Seals, Valerie Shalin
**Venue:** Proceedings of the 2024 Conference of the North American Chapter of the Association for Computational Linguistics: Human Language Technologies (Volume 1: Long Papers) (2024)
**Combined Score:** 0.24 (relevance: 0.16, notable: 0.34)
**Keywords:** LLMs, LLM, language models
**Abstract:** The development of highly fluent large language models (LLMs) has prompted increased interest in assessing their reasoning and problem-solving capabilities. We investigate whether several LLMs can solve a classic type of deductive reasoning problem from the cognitive science literature. The tested L...
**Links:** [PDF](https://aclanthology.org/2024.naacl-long.476.pdf)

### 30. Diagnosing the First-Order Logical Reasoning Ability Through LogicNLI

**Authors:** Jidong Tian, Yitian Li, Wenqing Chen et al.
**Venue:** Proceedings of the 2021 Conference on Empirical Methods in Natural Language Processing (2021)
**Combined Score:** 0.23 (relevance: 0.22, notable: 0.26)
**Keywords:** BERT, RoBERTa, XLNet, LogicNLI, benchmark
**Abstract:** Recently, language models (LMs) have achieved significant performance on many NLU tasks, which has spurred widespread interest for their possible applications in the scientific and social area. However, LMs have faced much criticism of whether they are truly capable of reasoning in NLU. In this work...
**Links:** [PDF](https://aclanthology.org/2021.emnlp-main.303.pdf)

### 31. LoC-Decomp: LLM Autoformalization via Logical Concept Decomposition and Iterative Feedback Correction

**Authors:** Jiangze Shi, Zhiwei Zhang, Baoquan Ma et al.
**Venue:** ICLR 2026 Poster (2026)
**Combined Score:** 0.23 (relevance: 0.12, notable: 0.40)
**Keywords:** LoC-Decomp, LLM, Lean 4, mathematics, PutnamBench
**Abstract:** Autoformalization—the process of converting natural language mathematical statements into machine-verifiable formal code—plays a critical role in ensuring the reliability of mathematical reasoning generated by large language models (LLMs). Recent studies show that LLMs exhibit strong potential in au...
**Links:** [PDF](https://openreview.net/pdf/932419c4cad3c01639810f758fc60372fe688122.pdf)

### 32. ReasonGraph: Visualization of Reasoning Methods and Extended Inference Paths

**Authors:** Zongqian Li, Ehsan Shareghi, Nigel Collier
**Venue:** Proceedings of the 63rd Annual Meeting of the Association for Computational Linguistics (Volume 3: System Demonstrations) (2025)
**Combined Score:** 0.22 (relevance: 0.13, notable: 0.37)
**Keywords:** LLMs
**Abstract:** Large Language Models (LLMs) reasoning processes are challenging to analyze due to their complexity and the lack of organized visualization tools. We present ReasonGraph, a web-based platform for visualizing and analyzing LLM reasoning processes. It supports both sequential and tree-based reasoning ...
**Links:** [PDF](https://aclanthology.org/2025.acl-demo.14.pdf) | [Code](https://github.com/ZongqianLi/ReasonGraph)

### 33. CoT-RAG: Integrating Chain of Thought and Retrieval-Augmented Generation to Enhance Reasoning in Large Language Models

**Authors:** Feiyang Li, Peng Fang, Zhan Shi et al.
**Venue:** Findings of the Association for Computational Linguistics: EMNLP 2025 (2025)
**Combined Score:** 0.22 (relevance: 0.16, notable: 0.31)
**Keywords:** reasoning tasks, CoT-RAG, graph
**Abstract:** Chain-of-thought (CoT) reasoning boosts large language models’ (LLMs) performance on complex tasks but faces two key limitations: a lack of reliability when solely relying on LLM-generated reasoning chains and interference from natural language reasoning steps with the models’ inference process, als...
**Links:** [PDF](https://aclanthology.org/2025.findings-emnlp.168.pdf) | [Code](https://github.com/hustlfy123/CoT-RAG.)

### 34. When Reasoning Collapses: A Depth-Aware Probe into LLM Reasoning (Student Abstract)

**Authors:** Azka Ikramullah, Abdul Majeed, Kyunghyun Lee et al.
**Venue:** Proceedings of the AAAI Conference on Artificial Intelligence (2026)
**Combined Score:** 0.22 (relevance: 0.09, notable: 0.40)
**Keywords:** LLM, GPT-5, ProofWriter, LLMs, CLUTRR
**Abstract:** Large language models (LLMs) often perform better when prompted to explain their reasoning, but it remains unclear how well such gains persist as reasoning depth increases. In this work, we propose a depth-aware evaluation framework alongside the performance results on two structured datasets: CLUTR...
**Links:** [PDF](https://ojs.aaai.org/index.php/AAAI/article/download/42223/46184)

### 35. Structured Reasoning for LLMs: A Unified Framework for Efficiency and Explainability

**Authors:** Yubo Dong, Hehe Fan, Linchao Zhu et al.
**Venue:** ICLR 2026 Poster (2026)
**Combined Score:** 0.22 (relevance: 0.09, notable: 0.40)
**Keywords:** planning, MaxFlow reward, LCS reward, structured tags, LLM
**Abstract:** Recent Large Language Models (LLMs) have made remarkable progress, but they still struggle with complex reasoning tasks such as logical deduction and planning. This is partly because they rely primarily on token-level probability relationships, which limits their ability to reason effectively. 
In t...
**Links:** [PDF](https://openreview.net/pdf/2149d9d2038113e9b0896c21a7d5c2a750017ce7.pdf)

### 36. Improving Large Language Models in Event Relation Logical Prediction

**Authors:** Meiqi Chen, Yubo Ma, Kaitao Song et al.
**Venue:** Proceedings of the 62nd Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers) (2024)
**Combined Score:** 0.21 (relevance: 0.13, notable: 0.34)
**Keywords:** fine-tuning, LLMs, LLM-ERL
**Abstract:** Event relations are crucial for narrative understanding and reasoning. Governed by nuanced logic, event relation extraction (ERE) is a challenging task that demands thorough semantic understanding and rigorous logical reasoning. In this paper, we conduct an in-depth investigation to systematically e...
**Links:** [PDF](https://aclanthology.org/2024.acl-long.512.pdf) | [Code](https://github.com/chenmeiqii/teach-llm-lr)

### 37. A Theoretical Study on Bridging Internal Probability and Self-Consistency for LLM Reasoning

**Authors:** Zhi Zhou, Yuhao Tan, Zenan Li et al.
**Venue:** NeurIPS 2025 poster (2025)
**Combined Score:** 0.21 (relevance: 0.11, notable: 0.37)
**Keywords:** LLM reasoning, perplexity, RPC
**Abstract:** Test-time scaling seeks to improve the reasoning performance of large language models (LLMs) by adding computational resources. A prevalent approach within the field is *sampling-based test-time scaling methods*, which enhance reasoning by generating multiple reasoning paths for a given input during...
**Links:** [PDF](https://openreview.net/pdf/73a0607365582aedefc2167e27fb239c96092223.pdf) | [Code](https://github.com/WNJXYK/RPC)

### 38. An Empirical Study of LLM Reasoning Ability Under Strict Output Length Constraint

**Authors:** Yi Sun, Han Wang, Jiaqiang Li et al.
**Venue:** Proceedings of the 2025 Conference on Empirical Methods in Natural Language Processing (2025)
**Combined Score:** 0.21 (relevance: 0.11, notable: 0.37)
**Keywords:** reasoning, empirical study, prompting, latency mapping
**Abstract:** Recent work has demonstrated the remarkable potential of Large Language Models (LLMs) in test-time scaling. By making models think before answering, they are able to achieve much higher accuracy with extra inference computation.However, in many real-world scenarios, models are used under time constr...
**Links:** [PDF](https://aclanthology.org/2025.emnlp-main.389.pdf) | [Code](https://github.com/time-is-up/time-is-up.github.io)

### 39. StructuThink: Reasoning with Task Transition Knowledge for Autonomous LLM-Based Agents

**Authors:** Haiyu Zhao, Zhenyu Guo, Chunhong Zhang et al.
**Venue:** Findings of the Association for Computational Linguistics: EMNLP 2025 (2025)
**Combined Score:** 0.21 (relevance: 0.15, notable: 0.31)
**Keywords:** decision-making, TTKG, LLM, StructuThink, embodied AI
**Abstract:** Decision-making tasks have highlighted fundamental challenges in grounding decisions within real-world contexts. Traditional decision knowledge utilization methods often struggle to effectively integrate structured decision constraints, limiting their ability to decompose high-level tasks, maintain ...
**Links:** [PDF](https://aclanthology.org/2025.findings-emnlp.1331.pdf)

### 40. Exposing the Achilles’ Heel: Evaluating LLMs Ability to Handle Mistakes in Mathematical Reasoning

**Authors:** Joykirat Singh, Akshay Nambi, Vibhav Vineet
**Venue:** Proceedings of the 63rd Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers) (2025)
**Combined Score:** 0.21 (relevance: 0.10, notable: 0.37)
**Keywords:** benchmarking, GPT-4o, GPT-4, OpenAI o1, MWP-MISTAKE
**Abstract:** Large Language Models (LLMs) have significantly impacted the field of Math Word Problems (MWPs), transforming how these problems are approached and solved, particularly in educational contexts. However, existing evaluations often focus on final accuracy, neglecting the critical aspect of reasoning c...
**Links:** [PDF](https://aclanthology.org/2025.acl-long.1313.pdf)

### 41. Multi-LogiEval: Towards Evaluating Multi-Step Logical Reasoning Ability of Large Language Models

**Authors:** Nisarg Patel, Mohith Kulkarni, Mihir Parmar et al.
**Venue:** Proceedings of the 2024 Conference on Empirical Methods in Natural Language Processing (2024)
**Combined Score:** 0.21 (relevance: 0.12, notable: 0.34)
**Keywords:** GPT-4, ChatGPT, Gemini-Pro, Orca, Mistral
**Abstract:** As Large Language Models (LLMs) continue to exhibit remarkable performance in natural language understanding tasks, there is a crucial need to measure their ability for human-like multi-step logical reasoning. Existing logical reasoning evaluation benchmarks often focus primarily on simplistic singl...
**Links:** [PDF](https://aclanthology.org/2024.emnlp-main.1160.pdf) | [Code](https://github.com/mihir3009/multi-logieval)

### 42. Exploring Self-supervised Logic-enhanced Training for Large Language Models

**Authors:** Fangkai Jiao, Zhiyang Teng, Bosheng Ding et al.
**Venue:** Proceedings of the 2024 Conference of the North American Chapter of the Association for Computational Linguistics: Human Language Technologies (Volume 1: Long Papers) (2024)
**Combined Score:** 0.21 (relevance: 0.12, notable: 0.34)
**Keywords:** LogicLLM, FLAN-T5, LLaMA, ReClor, LogiQA-v2
**Abstract:** Traditional attempts to enhance the logical reasoning abilities of language models often rely on supervised fine-tuning, limiting their generalization to new tasks or domains. Large Language Models (LLMs), with their capacity to condense vast knowledge, can effectively tackle many tasks. Yet, our ex...
**Links:** [PDF](https://aclanthology.org/2024.naacl-long.53.pdf) | [Code](https://github.com/sparkjiao/merit-v2)

### 43. FactEval: Evaluating the Robustness of Fact Verification Systems in the Era of Large Language Models

**Authors:** Mamta, Oana Cocarascu
**Venue:** Proceedings of the 2025 Conference of the Nations of the Americas Chapter of the Association for Computational Linguistics: Human Language Technologies (Volume 1: Long Papers) (2025)
**Combined Score:** 0.20 (relevance: 0.09, notable: 0.37)
**Keywords:** LLMs, misinformation, FactEval, FEVER, benchmark
**Abstract:** Whilst large language models (LLMs) have made significant advances in every natural language processing task, studies have shown that these models are vulnerable to small perturbations in the inputs, raising concerns about their robustness in the real-world. Given the rise of misinformation online a...
**Links:** [PDF](https://aclanthology.org/2025.naacl-long.534.pdf)

### 44. Are Your LLMs Capable of Stable Reasoning?

**Authors:** Junnan Liu, Hongwei Liu, Linchen Xiao et al.
**Venue:** Findings of the Association for Computational Linguistics: ACL 2025 (2025)
**Combined Score:** 0.20 (relevance: 0.13, notable: 0.31)
**Keywords:** LLM evaluation, G-Pass@k
**Abstract:** The rapid advancement of large language models (LLMs) has shown remarkable progress in complex reasoning tasks. However, a significant disparity exists between benchmark performances and real-world applications. We attribute this gap primarily to current evaluation protocols and metrics, which inade...
**Links:** [PDF](https://aclanthology.org/2025.findings-acl.905.pdf) | [Code](https://github.com/open-compass/gpassk)

### 45. Reasoning in Token Economies: Budget-Aware Evaluation of LLM Reasoning Strategies

**Authors:** Junlin Wang, Siddhartha Jain, Dejiao Zhang et al.
**Venue:** Proceedings of the 2024 Conference on Empirical Methods in Natural Language Processing (2024)
**Combined Score:** 0.20 (relevance: 0.10, notable: 0.34)
**Keywords:** reasoning, Reflexion
**Abstract:** A diverse array of reasoning strategies has been proposed to elicit the capabilities of large language models. However, in this paper, we point out that traditional evaluations which focus solely on performance metrics miss a key factor: the increased effectiveness due to additional compute. By over...
**Links:** [PDF](https://aclanthology.org/2024.emnlp-main.1112.pdf)

### 46. Teaching-Inspired Integrated Prompting Framework: A Novel Approach for Enhancing Reasoning in Large Language Models

**Authors:** Wenting Tan, Dongxiao Chen, Jieting Xue et al.
**Venue:** Proceedings of the 31st International Conference on Computational Linguistics: Industry Track (2025)
**Combined Score:** 0.20 (relevance: 0.12, notable: 0.31)
**Keywords:** prompt design, LLM, GPT-4, mathematics, MathMC
**Abstract:** Large Language Models (LLMs) exhibit impressive performance across various domains but still struggle with arithmetic reasoning tasks. Recent work shows the effectiveness of prompt design methods in enhancing reasoning capabilities. However, these approaches overlook crucial requirements for prior k...
**Links:** [PDF](https://aclanthology.org/2025.coling-industry.69.pdf) | [Code](https://github.com/sallytan13/teaching-inspired-prompting)

### 47. Assessing Factual Reliability of Large Language Model Knowledge

**Authors:** Weixuan Wang, Barry Haddow, Alexandra Birch et al.
**Venue:** Proceedings of the 2024 Conference of the North American Chapter of the Association for Computational Linguistics: Human Language Technologies (Volume 1: Long Papers) (2024)
**Combined Score:** 0.19 (relevance: 0.09, notable: 0.34)
**Keywords:** MONITOR, FKTC
**Abstract:** The factual knowledge of LLMs is typically evaluated using accuracy, yet this metric does not capture the vulnerability of LLMs to hallucination-inducing factors like prompt and context variability. How do we evaluate the capabilities of LLMs to consistently produce factually correct answers? In thi...
**Links:** [PDF](https://aclanthology.org/2024.naacl-long.46.pdf) | [Code](https://github.com/Vicky-Wil/MONITOR)

### 48. Consistency Analysis of ChatGPT

**Authors:** Myeongjun Jang, Thomas Lukasiewicz
**Venue:** Proceedings of the 2023 Conference on Empirical Methods in Natural Language Processing (2023)
**Combined Score:** 0.19 (relevance: 0.11, notable: 0.31)
**Keywords:** ChatGPT, GPT-4, AI reliability
**Abstract:** ChatGPT has gained a huge popularity since its introduction. Its positive aspects have been reported through many media platforms, and some analyses even showed that ChatGPT achieved a decent grade in professional exams, adding extra support to the claim that AI can now assist and even replace human...
**Links:** [PDF](https://aclanthology.org/2023.emnlp-main.991.pdf) | [Code](https://github.com/arthik444/ChatGPT-DevConvoAnalysis)

### 49. Towards Reasoning in Large Language Models: A Survey

**Authors:** Jie Huang, Kevin Chen-Chuan Chang
**Venue:** Findings of the Association for Computational Linguistics: ACL 2023 (2023)
**Combined Score:** 0.16 (relevance: 0.10, notable: 0.25)
**Keywords:** reasoning, LLMs, survey
**Abstract:** Reasoning is a fundamental aspect of human intelligence that plays a crucial role in activities such as problem solving, decision making, and critical thinking. In recent years, large language models (LLMs) have made significant progress in natural language processing, and there is observation that ...
**Links:** [PDF](https://aclanthology.org/2023.findings-acl.67.pdf) | [Code](https://github.com/jeffhj/lm-reasoning)

### 50. What Can Neural Networks Reason About?

**Authors:** Keyulu Xu, Jingling Li, Mozhi Zhang et al.
**Venue:** International Conference on Learning Representations (2020)
**Combined Score:** 0.16 (relevance: 0.11, notable: 0.23)
**Keywords:** reasoning, Neural Networks, MLP, Deep Learning, analysis
**Links:** [PDF](https://openreview.net/pdf/774321839e2c42db9faccc9852dec473e44d018a.pdf) | [Code](https://github.com/NNReasoning/What-Can-Neural-Networks-Reason-About)

## 4. Summary

- **Total papers**: 50
- **Year range**: [2020, 2026]
- **Papers with code**: 28/50
- **Top authors**: Kai Chen, Arijit Khan, Armin Toroghi, Ali Pesaranghader, Scott Sanner, Mihir Parmar, Nisarg Patel, Neeraj Varshney

---
*Report generated by LexiconArxiv research_topic API*