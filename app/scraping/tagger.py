"""Auto-tag jobs with categories based on title + description keywords."""
from __future__ import annotations

import re

# Each category: (label, list of patterns)
# Patterns are matched with word boundaries against title + description (lowered).
CATEGORIES: list[tuple[str, list[str]]] = [
    ("AI/ML", [
        r"artificial intelligence", r"\bai\b", r"machine learning", r"\bml\b",
        r"deep learning", r"\bdl\b", r"neural network", r"generative ai",
        r"genai", r"\bllm\b", r"large language model", r"foundation model",
        r"reinforcement learning", r"supervised learning", r"unsupervised learning",
        r"model training", r"mlops", r"ml engineer", r"ai engineer",
    ]),
    ("NLP", [
        r"\bnlp\b", r"natural language processing", r"natural language understanding",
        r"text mining", r"sentiment analysis", r"language model", r"chatbot",
        r"speech recognition", r"text generation", r"transformer",
        r"information extraction", r"named entity", r"\bner\b",
    ]),
    ("Computer Vision", [
        r"computer vision", r"\bcv\b(?!.*cover letter)", r"image recognition",
        r"object detection", r"image processing", r"image segmentation",
        r"video analysis", r"point cloud", r"lidar", r"\bocr\b",
        r"image classification", r"visual recognition", r"3d vision",
    ]),
    ("Data Science", [
        r"data scien", r"data analy", r"business intelligence",
        r"\bbi\b", r"data engineer", r"data mining", r"big data",
        r"statistical", r"analytics engineer", r"data warehouse",
        r"etl\b", r"data pipeline", r"dbt\b", r"power ?bi", r"tableau",
    ]),
    ("Robotics", [
        r"roboti", r"autonomous", r"ros\b", r"mechatron", r"embedded.{0,20}system",
        r"control system", r"sensor fusion", r"slam\b", r"actuator",
    ]),
    ("DevOps/Cloud", [
        r"devops", r"\bsre\b", r"site reliability", r"kubernetes", r"\bk8s\b",
        r"docker", r"terraform", r"cloud engineer", r"infrastructure",
        r"\baws\b", r"\bgcp\b", r"azure", r"ci/?cd",
    ]),
    ("Backend", [
        r"backend", r"back-end", r"server.{0,10}side", r"api develop",
        r"microservice", r"\bjava\b(?!script)", r"\bgo\b.{0,10}develop",
        r"rust.{0,10}develop", r"python.{0,10}develop", r"\bc\+\+",
    ]),
    ("Frontend", [
        r"frontend", r"front-end", r"react", r"angular", r"vue\.?js",
        r"typescript.{0,10}develop", r"ui develop", r"web develop",
    ]),
    ("Security", [
        r"cyber.?security", r"information security", r"pen.?test", r"security engineer",
        r"\bsoc\b", r"vulnerability", r"threat", r"infosec",
    ]),
    ("Research", [
        r"research", r"r&d\b", r"forschung", r"wissenschaft",
    ]),
    ("Design", [
        r"\bux\b", r"\bui\b", r"design", r"figma", r"user experience",
        r"product design", r"graphic design",
    ]),
    ("Finance", [
        r"financ", r"accounting", r"buchhal", r"controlling", r"audit",
        r"tax\b", r"steuer",
    ]),
    ("Marketing", [
        r"marketing", r"seo\b", r"content.{0,10}(manag|strat|creat)",
        r"social media", r"growth",
    ]),
    ("HR", [
        r"\bhr\b", r"human resource", r"recruiting", r"talent acquisition",
        r"people.{0,10}(ops|oper|cult)", r"personal",
    ]),
]

_COMPILED = [(label, [re.compile(p, re.IGNORECASE) for p in patterns])
             for label, patterns in CATEGORIES]


def compute_categories(title: str, description: str | None = None) -> str:
    """Return comma-separated category labels for a job."""
    text = f"{title} {description or ''}".lower()
    matched: list[str] = []
    for label, patterns in _COMPILED:
        if any(p.search(text) for p in patterns):
            matched.append(label)
    return ", ".join(matched)
