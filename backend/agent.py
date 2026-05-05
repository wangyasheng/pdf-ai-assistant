import os
from typing import List
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser

class ExamQuestion(BaseModel):
    question: str = Field(description="题目内容")
    options: List[str] = Field(description="选项列表")
    answer: str = Field(description="正确答案字母")
    analysis: str = Field(description="详细解析")

class DeepSeekAgent:
    def __init__(self):
        self.llm = ChatOpenAI(
            model='deepseek-chat',
            openai_api_key="sk-4aab669c8d7e45c9ae5782d373d44d5b",
            openai_api_base="https://api.deepseek.com",
            temperature=0.7
        )
        self.parser = PydanticOutputParser(pydantic_object=ExamQuestion)

    def generate_question(self, context, question=None):
        """
        兼容处理：
        如果只有 context，就当做知识点生成题目。
        如果有 question，就当做是针对内容的问答。
        """
        # 如果有 question 参数，说明是用户在 Streamlit 里的提问对话
        if question:
            prompt = ChatPromptTemplate.from_template(
                "参考背景内容：\n{context}\n\n问题：{question}\n请直接给出详细回答。"
            )
            chain = prompt | self.llm
            res = chain.invoke({"context": context, "question": question})
            return res.content  # 返回字符串
        
        # 否则，走你原来的“命题专家”逻辑
        prompt = ChatPromptTemplate.from_template(
            "你是一个命题专家。请根据以下内容提供一道历年真题。\n{format_instructions}\n内容：{context}"
        )
        chain = prompt | self.llm
        res = chain.invoke({
            "context": context,
            "format_instructions": self.parser.get_format_instructions()
        })
        return self.parser.parse(res.content) # 返回结构化对象

    def judge(self, q, u, c):
        prompt = ChatPromptTemplate.from_template("题目：{q}\n正确答案：{c}\n用户答案：{u}\n请判断正误并点评。")
        return (prompt | self.llm).invoke({"q": q, "u": u, "c": c}).content