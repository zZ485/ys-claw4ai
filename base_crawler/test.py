from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import requests
import json
import time
import os
from webdriver_manager.chrome import ChromeDriverManager


def get_cookies_via_selenium():
    """
    使用Selenium模拟浏览器访问，自动获取百度cookies
    """
    print("正在启动浏览器模拟...")

    # 配置Chrome选项
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # 无头模式，不显示浏览器窗口
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36"
    )

    # 启动浏览器
    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()), options=chrome_options
    )

    try:
        # 访问百度百科页面
        target_url = "https://baike.baidu.com/pic/%E5%B9%BF%E8%A5%BF%E5%A3%AE%E6%97%8F%E8%87%AA%E6%B2%BB%E5%8C%BA/163178/0/10dfa9ec8a13632762d0bdb159d7b7ec08fa503d69a2?fr=lemma&fromModule=lemma_content-image"
        print(f"正在访问: {target_url}")

        driver.get(target_url)

        # 等待页面加载完成，确保cookies已设置
        print("等待页面加载和cookies设置...")
        time.sleep(5)  # 给页面足够时间加载和设置cookies

        # 获取所有cookies
        cookies = driver.get_cookies()
        print(f"成功获取 {len(cookies)} 个cookies")

        # 将Selenium cookies格式转换为requests可用的格式
        cookie_dict = {}
        for cookie in cookies:
            cookie_dict[cookie["name"]] = cookie["value"]

        # 打印关键cookies
        print("获取到的关键cookies:")
        for key in ["BDUSS", "STOKEN", "BAIDUID", "BIDUPSID"]:
            if key in cookie_dict:
                print(f"  {key}: {cookie_dict[key][:20]}...")  # 只显示前20个字符

        return cookie_dict

    except Exception as e:
        print(f"Selenium获取cookies时出错: {e}")
        return {}

    finally:
        # 关闭浏览器
        driver.quit()
        print("浏览器已关闭")


def make_api_request(cookies):
    """
    使用获取到的cookies发起API请求
    """
    url = "https://baike.baidu.com/lemma/api/image/album?lemmaId=163178&albumId=0"

    headers = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,ja;q=0.7",
        "sec-ch-ua": '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "x-bk-token": "eyJwYWdlVXJsIjoiL3BpYy8lRTUlQjklQkYlRTglQTUlQkYlRTUlQTMlQUUlRTYlOTclOEYlRTglODclQUElRTYlQjIlQkIlRTUlOEMlQkEvMTYzMTc4LzAvMTBkZmE5ZWM4YTEzNjMyNzYyZDBiZGIxNTlkN2I3ZWMwOGZhNTAzZDY5YTI_ZnI9bGVtbWEmZnJvbU1vZHVsZT1sZW1tYV9jb250ZW50LWltYWdlIiwiZXhwaXJlVGltZSI6MTc2NTc5MDE3Nn0.2svC_lBEzqFUSauW_XkdUvYZgn2Mhkxy1xpMowQDk2Q",
        "referer": "https://baike.baidu.com/pic/%E5%B9%BF%E8%A5%BF%E5%A3%AE%E6%97%8F%E8%87%AA%E6%B2%BB%E5%8C%BA/163178/0/10dfa9ec8a13632762d0bdb159d7b7ec08fa503d69a2?fr=lemma&fromModule=lemma_content-image",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
    }

    try:
        print("正在发起API请求...")
        response = requests.get(url, headers=headers, cookies=cookies, timeout=15)

        print(f"API响应状态码: {response.status_code}")

        if response.status_code == 200:
            try:
                data = response.json()
                print("✅ API请求成功！")

                # 检查响应数据结构
                if "data" in data and "album" in data["data"]:
                    album = data["data"]["album"]
                    print(f"相册标题: {album.get('title', '未知')}")
                    print(f"图片数量: {len(album.get('picItems', []))}")

                    # 保存数据
                    filename = f"guangxi_images_{int(time.time())}.json"
                    with open(filename, "w", encoding="utf-8") as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    print(f"数据已保存到: {filename}")

                    return data
                else:
                    print("⚠️ 响应数据结构不符合预期")
                    print(
                        "响应内容:",
                        json.dumps(data, indent=2, ensure_ascii=False)[:500],
                    )
            except json.JSONDecodeError:
                print("❌ 响应不是有效的JSON格式")
                print("响应内容:", response.text[:500])
        else:
            print(f"❌ API请求失败: {response.status_code}")
            print("响应内容:", response.text[:500])

    except requests.exceptions.RequestException as e:
        print(f"❌ 请求异常: {e}")
    except Exception as e:
        print(f"❌ 未知错误: {e}")

    return None


def main():
    """
    主函数：获取cookies并发起API请求
    """
    print("=" * 60)
    print("百度百科图片API请求模拟器")
    print("=" * 60)

    # 第一步：使用Selenium获取cookies
    cookies = get_cookies_via_selenium()

    if not cookies:
        print("❌ 未能获取到cookies，程序终止")
        return

    print("\n" + "=" * 60)
    print("开始API请求")
    print("=" * 60)

    # 第二步：使用获取到的cookies发起API请求
    result = make_api_request(cookies)

    if result:
        print("\n✅ 程序执行成功！")
    else:
        print("\n❌ 程序执行失败")


if __name__ == "__main__":
    # 安装必要的包提示
    print("请确保已安装以下包:")
    print("pip install selenium requests webdriver-manager")
    print("-" * 60)

    main()
