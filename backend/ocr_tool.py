import base64
import io
import numpy as np
from PIL import Image
from paddleocr import PaddleOCR

class OCRTool:
    def __init__(self):
        # 懒加载：只有在第一次初始化时才加载模型
        # lang="ch" 支持中英文，use_angle_cls=True 自动纠正文字方向
        self.engine = None

    def _get_engine(self):
        if self.engine is None:
            self.engine = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
        return self.engine

    def recognize_base64(self, base64_str: str):
        """
        核心逻辑：输入 base64 字符串，输出识别后的文本
        """
        try:
            # 1. 自动处理 DataURL 前缀 (如 data:image/png;base64, )
            if "," in base64_str:
                base64_str = base64_str.split(",")[1]
            
            # 2. 解码并转换为 PIL 对象
            img_bytes = base64.b64decode(base64_str)
            img_pil = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            
            # 3. 转换为 Numpy 数组供 Paddle 使用
            img_np = np.array(img_pil)

            # 4. 执行识别
            ocr = self._get_engine()
            result = ocr.ocr(img_np, cls=True)

            # 5. 格式化结果
            full_text = ""
            details = []
            
            if result and result[0]:
                for line in result[0]:
                    text = line[1][0]      # 文本内容
                    confidence = line[1][1] # 置信度
                    full_text += text + "\n"
                    details.append({
                        "text": text,
                        "confidence": float(confidence),
                        "box": line[0] # 文字坐标 [左上, 右上, 右下, 左下]
                    })

            return {
                "success": True,
                "full_text": full_text.strip(),
                "details": details
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }

# 实例化单例，方便 server.py 直接调用
ocr_tool = OCRTool()