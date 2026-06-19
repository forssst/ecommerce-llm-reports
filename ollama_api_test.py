import requests
import json


def test_ollama_api():
    url = "http://localhost:11434/api/generate"


    payload = {
        'model':'qwen2.5:3b',
        'prompt':'Name three types of turtles',
        'stream': False

    }


    print('test')

    try:
        response = requests.post(url, json=payload)

        if response.status_code == 200:
            answer = response.json()
            print(answer['response'])
        else: print(f'błąd {response.status_code}')

    except Exception as e:
        print(f'nie udalo sie {e}')


if __name__ == "__main__":
    test_ollama_api()
        
