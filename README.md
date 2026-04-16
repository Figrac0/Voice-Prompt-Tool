# Voice Prompt Tool

Windows-only background диктовка для личного использования.

Текущий MVP умеет:

- глобальный hotkey `Ctrl + Shift`
- запись микрофона, пока hotkey удерживается
- быстрый live preview в активном текстовом поле во время речи
- финальную локальную транскрибацию через `faster-whisper` после отпускания hotkey
- лёгкую постобработку текста
- копирование в clipboard
- вставку в активное поле
- локальную историю в `data/history.json`
- очистку temp-файлов и логирование
- блокировку второго экземпляра приложения
- маленький always-on-top оверлей-индикатор (кружок) во время записи

MVP не умеет:

- cloud APIs
- LLM rewrite / paraphrase
- полноценный streaming ASR с идеальной построчной стабилизацией
- идеальную пунктуацию и идеальное распознавание без ошибок

## Как запускать

Требования:

- Windows
- Python 3.10+

Запуск:

```bat
cd voice_prompt_tool
run.bat
```

`run.bat` делает следующее:

- создаёт `.venv`, если его нет
- ставит зависимости из `requirements.txt`
- запускает приложение в текущем окне консоли

Альтернативный запуск без `bat`:

```powershell
python -m app
```

## Сборка отдельного приложения (`.exe`)

```powershell
.\build_exe.ps1
```

После сборки запускай:

`dist\VoicePromptTool\VoicePromptTool.exe`

Приложение стартует без консоли, в трее и с оверлеем-индикатором.

После старта:

- в трее появится иконка
- консоль останется открытой
- runtime-логи будут видны сразу

## Режим работы

1. Наведи фокус на текстовое поле.
2. Зажми `Ctrl + Shift`.
3. Пока говоришь, приложение пишет микрофон и периодически обновляет черновой текст прямо в активном поле.
4. Отпусти hotkey.
5. Черновой текст заменяется финальной локальной расшифровкой.
6. Финальный текст сохраняется в `data/history.json`.
7. Финальный текст копируется в clipboard.

Схема двухфазная:

- `live_preview` - быстрый, менее точный черновик во время речи
- `transcription` - более точный финальный проход после отпускания hotkey

Именно эта схема приближает поведение к Wispr Flow, но это не его копия.

## Конфиг

Главный файл настроек - `config.json`.

Основные поля:

- `hotkey.combination` - по умолчанию `ctrl+shift`
- `audio.sample_rate` - по умолчанию `16000`
- `audio.max_record_seconds` - по умолчанию `120`
- `transcription.model_size` - финальная модель, по умолчанию `medium`
- `transcription.language_mode` - `auto`, `ru`, `en`
- `transcription.device` - `auto`, `cpu` или другой поддерживаемый CTranslate2 device
- `transcription.compute_type` - `default`, `int8`, `float16` и т.д.
- `transcription.beam_size` - больше beam = медленнее, но обычно точнее
- `transcription.best_of` - больше candidates = медленнее, но обычно точнее
- `transcription.initial_prompt` - подсказка модели для диктовки
- `transcription.hotwords` - слова и product names, которые нужно распознавать стабильнее
- `live_preview.enabled` - включает черновой live preview
- `live_preview.model_size` - модель для preview, по умолчанию `base`
- `live_preview.update_interval_seconds` - как часто обновлять live preview
- `live_preview.min_audio_seconds` - минимальная длина snapshot перед preview
- `live_preview.max_preview_window_seconds` - сколько последнего аудио брать в preview snapshot
- `overlay.enabled` - показывать мини-индикатор на экране
- `overlay.size` - размер квадрата индикатора
- `overlay.recording_color` - цвет круга в записи (по умолчанию белый)
- `text_postprocess.auto_copy` - копировать итог в clipboard
- `text_postprocess.auto_paste` - вставлять текст в активное поле
- `text_postprocess.custom_replacements` - свои словарные замены после распознавания

Пример:

```json
{
  "transcription": {
    "model_size": "medium",
    "language_mode": "ru",
    "device": "auto",
    "compute_type": "default",
    "beam_size": 6,
    "best_of": 6,
    "initial_prompt": "Это голосовая диктовка на русском и английском. Распознавай слова дословно. Не придумывай слова, которых нет в аудио. Сохраняй естественные точки, запятые и вопросительные знаки.",
    "hotwords": "ChatGPT, OpenAI, React, TypeScript, Next.js"
  },
  "live_preview": {
    "enabled": true,
    "model_size": "base",
    "language_mode": "ru",
    "update_interval_seconds": 0.6,
    "min_audio_seconds": 0.5,
    "max_preview_window_seconds": 10.0
  },
  "text_postprocess": {
    "auto_copy": true,
    "auto_paste": true,
    "custom_replacements": {
      "чат gpt": "ChatGPT",
      "опен эй ай": "OpenAI",
      "реакт": "React"
    }
  }
}
```

## Как тюнить скорость и качество

Если нужен более быстрый отклик:

- оставь `live_preview.model_size: "base"`
- держи `transcription.model_size: "medium"`
- не ставь `large-v3` на CPU, если важна задержка

Если нужен более качественный финальный текст:

- попробуй `transcription.model_size: "medium"`
- оставь `language_mode: "ru"`, если диктуешь в основном по-русски
- дополняй `hotwords`
- заполняй `custom_replacements`

Если нужен агрессивный максимум качества:

- `transcription.model_size: "large-v3"`

Но на CPU это заметно увеличит задержку после отпускания hotkey.

## История

Файл истории - `data/history.json`.

Каждая запись содержит:

- `timestamp`
- `raw_text`
- `cleaned_text`
- `language_mode`
- `recording_duration_seconds`

История:

- ограничена `history_limit`
- пишется атомарно
- при порче файла автоматически восстанавливается
- последовательные дубли не сохраняются повторно

## Файлы и логи

- основной лог: `logs/voice_prompt_tool.log`
- bootstrap лог: `logs/bootstrap.log`
- временные wav: `temp/*.wav`
- модели: `models/`
- история: `data/history.json`

## Известные пределы

- Это локальная CPU/GPU-диктовка, а не облачный сервис.
- Live preview быстрее, но он менее точный, чем финальный проход.
- Финальная фраза может появляться не мгновенно, если модель тяжёлая или железо слабое.
- Если фокус уходит с нужного поля, auto-paste и live preview уйдут не туда.
- Пунктуация и вопросительные знаки улучшаются эвристиками, но не гарантируются идеально.
- До качества и latency Wispr Flow локальный `faster-whisper` без облака не дотягивает.
