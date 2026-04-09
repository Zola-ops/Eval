#!/usr/bin/env python3
import requests
import json

API_URL = "https://p6s8vpm3x5.coze.site/run"
TOKEN = "pat_fkhu2uHjHw3EvdqCi8FTGMbP1WIyE2TfKwfwNgfZAn7fW46WHLnUseFPRMhpQ2Gm"

def test_api():
    payload = {
        "query": "什么是《鬼灭之刃》？",
        "date": "",
        "demand": "",
        "answer": "《鬼灭之刃》是日本漫画家吾峠呼世晴创作的热血少年漫画"
    }
    
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json"
    }
    
    print("正在测试API连接...")
    print(f"URL: {API_URL}")
    print(f"Payload: {json.dumps(payload, ensure_ascii=False)}")
    print("\n发送请求...")
    
    try:
        response = requests.post(API_URL, json=payload, headers=headers, timeout=30)
        print(f"状态码: {response.status_code}")
        
        if response.status_code == 200:
            print("✓ API调用成功!")
            result = response.json()
            print(f"响应内容: {json.dumps(result, ensure_ascii=False, indent=2)}")
        else:
            print(f"✗ API调用失败!")
            print(f"错误响应: {response.text}")
            
    except Exception as e:
        print(f"✗ 发生异常: {str(e)}")

if __name__ == "__main__":
    test_api()
