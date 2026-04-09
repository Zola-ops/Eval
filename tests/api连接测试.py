#!/usr/bin/env python3
import requests
import json

API_URL = "https://p6s8vpm3x5.coze.site/run"
TOKEN = "pat_fkhu2uHjHw3EvdqCi8FTGMbP1WIyE2TfKwfwNgfZAn7fW46WHLnUseFPRMhpQ2Gm"

print("=" * 80)
print("API 连接测试")
print("=" * 80)

payload = {
    "query": "测试问题",
    "date": "",
    "demand": "",
    "answer": "测试回答"
}

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

print(f"\n1. API URL: {API_URL}")
print(f"2. Token: {TOKEN[:20]}...")
print(f"3. Payload: {json.dumps(payload, ensure_ascii=False)}")

print("\n" + "=" * 80)
print("发送API请求...")
print("=" * 80)

try:
    response = requests.post(API_URL, json=payload, headers=headers, timeout=30)
    
    print(f"\n状态码: {response.status_code}")
    print(f"响应头: {dict(response.headers)}")
    
    if response.status_code == 200:
        print("\n✓ API调用成功!")
        print(f"响应内容:")
        print(json.dumps(response.json(), ensure_ascii=False, indent=2))
    else:
        print(f"\n✗ API调用失败!")
        print(f"错误响应: {response.text}")
        
except requests.exceptions.Timeout:
    print("\n✗ 请求超时 (30秒)")
except requests.exceptions.ConnectionError as e:
    print(f"\n✗ 连接错误: {str(e)}")
except Exception as e:
    print(f"\n✗ 发生异常: {type(e).__name__}: {str(e)}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 80)
print("测试完成")
print("=" * 80)
