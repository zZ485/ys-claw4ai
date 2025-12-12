import asyncio
import re
import json
from playwright.async_api import async_playwright

async def get_fecu_token():
    """通过捕获网络请求获取FECU令牌"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36...'
        )
        page = await context.new_page()
        
        print("正在访问页面...")
        await page.goto('https://www.ebrun.com/newest/', wait_until='networkidle')
        await page.wait_for_timeout(2000)  # 确保JS执行完毕
        
        # 捕获请求以获取FECU令牌
        captured_token = None
        def handle_request(request):
            nonlocal captured_token
            url = request.url
            if '/more/' in url and 'FECU=' in url:
                match = re.search(r'FECU=([a-zA-Z0-9%+/=]+)', url)
                if match:
                    captured_token = match.group(1)
        
        page.on('request', handle_request)
        
        print("点击加载更多按钮以获取FECU令牌...")
        try:
            await page.click('#app > main > div.ebrun-global-content > section.main-module > div.button-group > a')
            await page.wait_for_timeout(3000)
        except Exception as e:
            print(f"点击按钮时出错: {e}")
            pass
        
        await browser.close()
        return captured_token

# async def save_fecu_token(token, filename='fecu_token.txt'):
#     """保存FECU令牌到文件"""
#     with open(filename, 'w') as f:
#         f.write(token)
#     print(f"FECU令牌已保存到 {filename}")

async def main():
    print("开始获取FECU令牌...")
    token = await get_fecu_token()
    
    if token:
        print(f"\n✅ 成功获取FECU参数:")
        print(token)
        # await save_fecu_token(token)
    else:
        print("\n❌ 未能获取FECU参数。")

if __name__ == '__main__':
    asyncio.run(main())
