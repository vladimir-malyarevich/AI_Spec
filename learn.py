# Импорт необходимых модулей
import os  # Для работы с файловой системой
import pickle  # Для сериализации/десериализации данных
from telebot import types  # Для работы с элементами интерфейса Telegram бота
from request import gpt_request  # Импорт функции для запросов к GPT-модели
import re  # Для работы с регулярными выражениями
from datetime import datetime  # Для работы с датой и временем

# Глобальный словарь для хранения активных сессий обучения
# Формат: {chat_id: session_data}
learning_sessions = {}

def init_learning_module(bot_instance):
    """Инициализация модуля с экземпляром бота"""
    global bot  # Делаем bot глобальной переменной
    bot = bot_instance  # Сохраняем экземпляр бота

def start_learning_session(message):
    """Начало сессии обучения - запрос темы у пользователя"""
    # Создаем клавиатуру с одной кнопкой "Отмена"
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("Отмена"))
    
    # Отправляем сообщение с запросом темы
    msg = bot.send_message(
        message.chat.id,  # ID чата
        "📖 Введите тему, которую хотите изучить:",  # Текст сообщения
        reply_markup=markup  # Прикрепляем клавиатуру
    )
    
    # Сохраняем состояние сессии в словаре
    learning_sessions[str(message.chat.id)] = {
        'stage': 'awaiting_topic',  # Текущий этап
        'message_id': msg.message_id  # ID сообщения для отслеживания
    }
    
    # Регистрируем обработчик следующего сообщения
    bot.register_next_step_handler(msg, process_topic_input)

def process_topic_input(message):
    """Обработка введенной темы с парсингом структурированных вопросов"""
    # Обработка команды отмены
    if message.text.lower() == 'отмена':
        cleanup_session(message.chat.id)  # Очищаем сессию
        return bot.send_message(message.chat.id, "Обучение отменено", reply_markup=types.ReplyKeyboardRemove())
    
    # Формируем промпт для GPT с четкими инструкциями по формату
    prompt = f"""
    Создай подробные учебные материалы, минимум 5 абзацев по теме: {message.text}
    Создай 5 вопросов по темe.
    Шаблон ответа:
    Теоретическая часть (структурированный текст с примерами)
    ---
    Вопросы по теме только с 1 вариантом правильного ответа. В каждом вопросе 4 варианта ответа. Задай нумерацию цифрами от 1 до 4 (никогда не используй буквы в нумерации) вопросов и ответов. Сделай так, чтобы вопросы было удобно считывать посредством программы. Пусть вопрос начинается со слова ";;Вопрос", затем идёт тело Вопроса и варианты Ответа и заканчивается словом "Ответ". После которого идёт номер правильного ответа. Слово "Ответ" не надо дублировать.
    """
    
    # Показываем индикатор набора текста
    bot.send_chat_action(message.chat.id, 'typing')
    # Отправляем запрос к GPT
    response = gpt_request(prompt)
    
    # Обработка ошибки генерации
    if not response:
        cleanup_session(message.chat.id)
        return bot.send_message(message.chat.id, "Ошибка при генерации материалов")

    # Парсинг ответа от GPT
    try:
        # Разделяем теорию и вопросы по разделителю ---
        if '---' in response:
            theory_part = response.split('---', 1)[:-1]  # Теоретическая часть
            questions_part = response.split('---', 1)[-1]  # Часть с вопросами
        elif 'Вопросы по теме' in response:
            theory_part = response.split('Вопросы по теме', 1)[:-1]
            questions_part = response.split('Вопросы по теме', 1)[-1]
        else:
            theory_part = response
            questions_part = ""
        
        # Обработка случая, когда theory_part - список
        if type(theory_part) == list:
            theory_part = ' '.join(theory_part)
        theory = theory_part.strip()  # Очищаем от лишних пробелов
        questions = []  # Список для хранения вопросов
        
        # Подготовка текста вопросов к парсингу
        questions_part = questions_part.replace('*','')  # Удаляем маркеры форматирования
        question_blocks = questions_part.split(';')[1:]  # Разбиваем по разделителю ;;
        
        # Парсинг каждого блока вопроса
        for block in question_blocks:
            if not block.strip():  # Пропускаем пустые блоки
                continue
                
            try:
                # Разбиваем блок на строки и очищаем их
                lines = [line.strip() for line in block.split('\n') if line.strip()]
                
                # Извлекаем текст вопроса (эвристически)
                if len(lines[0])>10:  # Если первая строка длинная - это вопрос
                    question_text = lines[0]
                else:  # Иначе вопрос во второй строке
                    question_text = lines[1]
                
                # Извлекаем варианты ответов (ищем строки с цифрами)
                options = []
                for line in lines[-6:-1]:  # Ищем в последних строках
                    if line and line[0].isdigit() and line[1] in ('.', ')'):
                        options.append(line[2:].strip())  # Добавляем вариант без номера
                
                # Извлекаем номер правильного ответа (из последней строки)
                answer_line = lines[-1]
                # Удаляем все нецифровые символы для получения номера
                correct_answer = int(re.sub(r'[^0-9]', '', answer_line))
                
                # Проверяем корректность данных и сохраняем вопрос
                if question_text and len(options) == 4 and correct_answer is not None and correct_answer <=4:
                    formatted_question = {
                        'text': question_text,  # Текст вопроса
                        'options': options,  # Варианты ответов
                        'correct': correct_answer,  # Номер правильного ответа (1-based)
                        'original_format': block  # Оригинальный текст для отладки
                    }
                    questions.append(formatted_question)    
            except Exception as e:
                print(f"Ошибка парсинга вопроса: {e}")
                continue
        
        # Проверяем, что получили хотя бы один вопрос
        if not questions:
            raise ValueError("Не удалось извлечь вопросы из ответа")
            
    except Exception as e:
        print(f"Ошибка парсинга ответа: {e}")
        cleanup_session(message.chat.id)
        return bot.send_message(message.chat.id, "Ошибка при обработке материалов. Попробуйте другую тему.")
    
    # Сохраняем данные в сессию
    learning_sessions[str(message.chat.id)] = {
        'stage': 'materials_shown',  # Текущий этап
        'theory': theory,  # Теоретическая часть
        'questions': questions,  # Список вопросов
        'current_question': 0,  # Индекс текущего вопроса
        'correct_answers': 0  # Счетчик правильных ответов
    }
    
    # Отправляем материалы пользователю
    send_learning_materials(message.chat.id, theory)
    
def send_learning_materials(chat_id, theory):
    """Отправка учебных материалов"""
    # Разбиваем теорию на части по 4000 символов (ограничение Telegram)
    max_length = 4000
    parts = [theory[i:i+max_length] for i in range(0, len(theory), max_length)]
    
    # Отправляем каждую часть отдельным сообщением
    for part in parts:
        bot.send_message(chat_id, part)
    
    # Создаем клавиатуру с вариантами действий
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton("Пройти тест"))
    markup.add(types.KeyboardButton("Отмена"))
    
    # Отправляем предложение пройти тест
    bot.send_message(
        chat_id,
        "📚 Материалы готовы. Хотите пройти тест для закрепления?",
        reply_markup=markup
    )
    # Регистрируем обработчик выбора пользователя
    bot.register_next_step_handler_by_chat_id(chat_id, handle_test_decision)

def handle_test_decision(message):
    """Обработка решения о прохождении теста"""
    # Обработка отмены
    if message.text.lower() == 'отмена':
        cleanup_session(message.chat.id)
        return bot.send_message(message.chat.id, "Обучение завершено", 
                              reply_markup=types.ReplyKeyboardRemove())
    
    # Обработка выбора теста
    if message.text.lower() == 'пройти тест':
        session = learning_sessions.get(str(message.chat.id))
        if session and 'questions' in session:
            session['stage'] = 'testing'  # Меняем этап на тестирование
            send_question_gpt(str(message.chat.id), 0)  # Начинаем с первого вопроса
        else:
            bot.send_message(message.chat.id, "Сессия устарела. Начните заново.")

def send_question_gpt(chat_id, question_idx):
    """Отправка вопроса теста"""
    session = learning_sessions.get(chat_id)
    # Проверяем, что сессия существует и вопросы не закончились
    if not session or question_idx >= len(session['questions']):
        return finish_test_session(chat_id)  # Завершаем тест
    
    question = session['questions'][question_idx]
    
    # Формируем текст сообщения с вопросом
    question_msg = (
        f"📝 Вопрос {question_idx + 1}/{len(session['questions'])}:\n"
        f"{question['text']}\n\n"
        f"Варианты ответов:\n"
    )
    # Добавляем варианты ответов с нумерацией
    for i, option in enumerate(question['options']):
        question_msg += f"{i+1}. {option}\n"
    
    # Создаем inline-клавиатуру с вариантами ответов
    markup = types.InlineKeyboardMarkup(row_width=2)
    for i, option in enumerate(question['options']):
        # Обрезаем длинные варианты ответов
        btn_text = f"{i+1}. {option[:20]}..." if len(option) > 20 else f"{i+1}. {option}"
        markup.add(types.InlineKeyboardButton(
            text=btn_text,
            # Формат callback_data: learntest_номервопроса_номерответа_номерправильного
            callback_data=f"learntest_{question_idx}_{i}_{question['correct']}"
        ))
    
    # Отправляем вопрос пользователю
    msg = bot.send_message(
        chat_id,
        question_msg,
        reply_markup=markup
    )
    
    # Сохраняем состояние
    session['current_question'] = question_idx  # Текущий вопрос
    session['last_question_msg'] = msg.message_id  # ID сообщения для редактирования

def finish_test_session(chat_id):
    """Завершение теста и вывод результатов"""
    session = learning_sessions.get(chat_id)
    if not session:
        return
    
    # Подсчет результатов
    total = len(session['questions'])
    correct = session['correct_answers']
    score = (correct / total) * 100
    
    # Сохраняем результаты
    save_test_results(chat_id, score)
    
    # Формируем сообщение с результатами
    result_msg = (
        f"📊 Тест завершен!\n"
        f"✅ Правильных ответов: {correct}/{total}\n"
        f"💯 Ваш результат: {score:.1f}%\n\n"
    )
    
    # Добавляем рекомендации в зависимости от результата
    if score >= 70:
        result_msg += "Отличный результат! Вы хорошо усвоили материал."
    elif score >= 50:
        result_msg += "Неплохо, но можно лучше. Рекомендуем повторить материал."
    else:
        result_msg += "Рекомендуем изучить материал еще раз."
    
    # Отправляем результаты
    bot.send_message(
        chat_id,
        result_msg,
        reply_markup=types.ReplyKeyboardRemove()
    )
    
    # Очищаем сессию
    cleanup_session(chat_id)

def save_test_results(user_id, score):
    """Сохранение результатов теста"""
    try:
        # Загружаем данные пользователя
        user_data = load_user_data()
        user_id_str = str(user_id)
        
        if user_id_str not in user_data:
            return False
        
        # Инициализируем историю обучения, если нет
        if 'learning_history' not in user_data[user_id_str]:
            user_data[user_id_str]['learning_history'] = []
        
        # Добавляем новый результат
        user_data[user_id_str]['learning_history'].append({
            'score': score,  # Результат в процентах
            'date': datetime.now().strftime("%Y-%m-%d %H:%M")  # Время прохождения
        })
        # Сохраняем обновленные данные
        save_user_data(user_data)
        return True
    except Exception as e:
        print(f"Ошибка сохранения результатов: {e}")
        return False

def cleanup_session(chat_id):
    """Очистка данных сессии и возврат в меню"""
    # Удаляем сессию из словаря
    if str(chat_id) in learning_sessions:
        del learning_sessions[str(chat_id)]
    
    # Создаем клавиатуру с кнопкой меню
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("Меню")
    
    # Отправляем сообщение с предложением вернуться в меню
    bot.send_message(
        chat_id,
        "Чтобы вернуться в меню нажмите",
        reply_markup=markup
    )

# Функции для работы с данными пользователей
def load_user_data():
    """Загрузка данных пользователей из файла"""
    if os.path.exists('user_data.pkl'):
        with open('user_data.pkl', 'rb') as f:  # Открываем файл для чтения
            return pickle.load(f)  # Десериализуем данные
    return {}  # Возвращаем пустой словарь, если файла нет

def save_user_data(data):
    """Сохранение данных пользователей в файл"""
    with open('user_data.pkl', 'wb') as f:  # Открываем файл для записи
        pickle.dump(data, f)  # Сериализуем и сохраняем данные