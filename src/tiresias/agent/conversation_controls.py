"""Deterministic speech acceptance and explicit response-language controls."""
from __future__ import annotations

import re

from tiresias.agent.policy import route_utterance
from tiresias.contracts import IntentKind

LANGUAGES={'en':'English','ru':'Russian'}


def language_command(text: str) -> str | None:
    norm=re.sub(r'\s+',' ',text.lower()).strip(' .!?')
    norm=re.sub(r'^(?:(?:can|could|would) you |please )+','',norm)
    match=re.fullmatch(r'(?:speak(?: in)?|switch(?: the language)? to|change (?:the )?language to|use) (english|russian)(?: language)?',norm)
    if match:
        return {'english':'en','russian':'ru'}[match[1]]
    if re.fullmatch(r'(?:говори|разговаривай|отвечай)(?: со мной)? (?:по[- ]русски|на русском)',norm):
        return 'ru'
    if re.fullmatch(r'(?:говори|разговаривай|отвечай)(?: со мной)? (?:по[- ]английски|на английском)',norm):
        return 'en'
    return None


def clean_request(text: str, *, busy: bool) -> str | None:
    value=text.strip()
    control={'стоп':'stop','подожди':'wait','погоди':'wait','повтори':'repeat',
             'медленнее':'slower','быстрее':'faster','проверь':'check this','проверь это':'check this'}.get(value.lower().strip(' .!?'))
    if control:
        return control
    if not value or value.endswith(('-', '—')):
        return None
    if re.fullmatch(r'[\[(].*[\])]',value):
        return None
    value=re.sub(r'^(?:(?:um|uh|erm|hmm|ah|oh)[\s,.!?-]+)+','',value,flags=re.I)
    value=re.sub(r'^(?:(?:а[ -]*){2,}|(?:м[ -]*){2,}|(?:э[ -]*){2,})[, .!?]+','',value,flags=re.I).strip()
    norm=re.sub(r'[^\w\s]',' ',value.lower())
    words=norm.split()
    if not words:
        return None
    backchannels={'yes','yeah','yep','okay','ok','sure','thanks','thank','you',
                  'uh','um','ah','oh','hmm','mm','mhm','eh','а','э','м','да','нет','ага',
                  'угу','ну','всё','все','таки','спасибо','хорошо'}
    if all(word in backchannels for word in words):
        return None
    if re.fullmatch(r'(?:да\s+)*(?:я вижу|i see)(?:\s+да)*',norm.strip()):
        return None
    if all(len(word)==1 for word in words):
        return None
    # Reuse the real router for explicit requests. A separate prefix whitelist
    # must not silently remove existing stop/repeat/find/check controls. With
    # no TaskContext, the router's ambiguous bare-product shortcut is disabled.
    if route_utterance(value,None).kind!=IntentKind.ASK_CLARIFICATION:
        return value
    question=bool(re.match(r'^(?:(?:and|but|so|а|ну)\s+)*(?:what|where|how|which|who|when|why|can|could|would|should|is|are|am|does|do|did|что|где|сколько|какой|какая|какие|какое|как|я правильно)\b',norm))
    command=bool(re.match(r'^(?:please\s+)?(?:check|read|find|locate|look|describe|tell|show|stop|wait|hold|pause|repeat|slower|faster|slow|speed|listen|cancel|use|speak|switch|change|найди|покажи|прочитай|проверь|стоп|повтори|подожди|говори|отвечай)\b',norm))
    greeting=norm.strip() in {'hello','hi','hey','hello there','привет'}
    if busy and not (question or command):
        return None
    if not busy and not (question or command or greeting) and len(words)>3:
        return None
    return value


def localize(text: str, language: str) -> str:
    if language!='ru':
        return text
    fixed={
        "I'm listening.":'Я слушаю.',
        'Taking a look.':'Смотрю.',
        'Still checking.':'Ещё проверяю.',
        'Checking that.':'Проверяю.',
        "I couldn't finish that look. Could you try again?":'Не удалось закончить проверку. Попробуйте ещё раз.',
        "I'm not getting a current camera view. Check that your video is on.":'Нет текущего изображения с камеры. Проверьте, включено ли видео.',
        "The image service didn't respond. Say try again and I'll take another look.":'Сервис изображения не ответил. Попросите проверить ещё раз.',
        "I've reached the image limit for this call. Call again to keep going.":'Достигнут лимит изображений для этого звонка. Перезвоните, чтобы продолжить.',
        "I'm here. What would you like me to look at?":'Я здесь. На что посмотреть?',
        'Okay. What would you like to know?':'Что вы хотите узнать?',
        'I need a clearer look at the label — hold it steady.':'Подержите этикетку неподвижно, чтобы я мог её прочитать.',
        "That view's gone. Hold it still and try again.":'Изображение изменилось. Подержите предмет неподвижно и повторите.',
        "A live helper isn't connected yet. I can take another look with you.":'Помощник сейчас не подключён. Я могу посмотреть ещё раз.',
        'I need a fresh check before I can repeat that.':'Сначала нужно заново проверить изображение.',
        'Okay, a bit slower.':'Хорошо, немного медленнее.',
        'Okay, a bit faster.':'Хорошо, немного быстрее.',
        "I can't help with dosing or crossing. I can read a regular product label though.":'Я не могу советовать дозировки или переход дороги, но могу прочитать обычную этикетку.',
        'Not sure on this one. Hold it steady, or ask a person.':'Пока не уверен. Подержите предмет неподвижно или попросите человека помочь.',
        'Profile entry cancelled.':'Ввод профиля отменён.',
        'Your saved voice preferences are loaded.':'Сохранённые настройки голоса загружены.',
        'What should I look for? Name the product, or hold a label up and say check this.':'Что найти? Назовите предмет или покажите этикетку и попросите проверить.',
    }
    if text in fixed:
        return fixed[text]
    if text.startswith('The label says '):
        return 'На этикетке написано: '+text[len('The label says '):]
    patterns=[
        (r'^Checking (.+)\.$',r'Проверяю \1.'),
        (r'^Okay [—–-] looking for (.+)\.$',r'Хорошо, ищу \1.'),
        (r'^This one says (.+)\.$',r'На этом написано: \1.'),
        (r"^That's not (.+)\. Show me the one you meant\.$",r'Это не \1. Покажите нужный предмет.'),
        (r'^I can see (.+)\. Hold the name still and say check this\.$',r'Я вижу: \1. Подержите название неподвижно и попросите проверить.'),
        (r'^Might be (.+)\. Hold the name still and say check this\.$',r'Возможно, это \1. Подержите название неподвижно и попросите проверить.'),
        (r'^I partly see (.+)\. Hold the name still for a clearer look\.$',r'Частично вижу: \1. Подержите название неподвижно.'),
        (r'^I can read (.+), but not the rest of the name yet\. Turn the label toward the camera\.$',r'Могу прочитать \1, но остальное пока не видно. Поверните этикетку к камере.'),
        (r'^Using (.+)\.$',r'Использую \1.'),
    ]
    for pattern,replacement in patterns:
        if re.match(pattern,text):
            return re.sub(pattern,replacement,text)
    return text
