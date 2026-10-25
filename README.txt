An intuitive GUI tool for effortless dataset image captioning (batch or one-by-one) and translation. Seamlessly integrates with your standalone LLM server.
To run the application, you will need a virtual environment with Python 3.12.10 and pip install gradio installed inside it. You also need to launch an LLM server, such as llama.cpp (llama-server.exe or any other), without reasoning.


TextImageGradioApp4 - приложение редактирования.


caption_images - подписать картинки
translate_text_files - перевести тексты
caption_one_image.py - описать одну картинку (путь или имя), подпись перезаписывается в testTxt:
    caption_one_image.py "имя_картинки.jpg"
translate_one_text.py - перевести один текст в testEn (можно передать имя картинки):
    translate_one_text.py "имя_файла.txt"


В приложении: «Описать картинку» и «Перевести текст» работают для выбранной картинки,
кнопки «Описать все картинки» и «Перевести описания» - под спойлером «Пакетная обработка».
Все пути и адрес сервера берутся только из Config.txt (ключи testImg, testTxt, testEn, api_url).
Если llama-server не запущен, приложение не падает:
текст ошибки виден в поле «Журнал скриптов».


Для запуска потребуется виртуальная среда, Python 3.12.10 и в виртуальной среде pip install Gradio, Запустить сервер с LLM моделью, llama.cpp llama-server.exe (или любой другой) без резонинга.
