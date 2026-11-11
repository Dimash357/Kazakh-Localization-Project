"""Generate the synthetic demo ARB files in examples/.

The real Grand Mobile files are confidential and must not be committed; these ~90 strings
imitate their structure. `intl_kk.arb` contains hand-made errors listed in `expected_kk.json`.
Run: python3 scripts/make_examples.py
"""

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "examples"

# key, ru, kk, uz, en, description
ROWS = [
    ("app_title", "Grand Mobile", "Grand Mobile", "Grand Mobile", "Grand Mobile", None),
    ("menu_play_button", "Играть", "Ойнау", "Oʻynash", "Play", "Кнопка в главном меню"),
    ("menu_settings_button", "Настройки", "Баптаулар", "Sozlamalar", "Settings", None),
    ("menu_exit_button", "Выход", "Шығу", "Chiqish", "Exit", None),
    ("common_close", "Закрыть", "Жабу", "Yopish", "Close", None),
    ("dialog_close_button", "Закрыть", "Жабу", "Yopish", "Close", None),
    ("inventory_close", "Закрыть", "Жабу", "Yopish", "Close", None),
    ("shop_close_button", "Закрыть", "Жабу", "Yopish", "Close", None),
    ("common_cancel", "Отмена", "Бас тарту", "Bekor qilish", "Cancel", None),
    ("common_confirm", "Подтвердить", "Растау", "Tasdiqlash", "Confirm", None),
    ("common_save", "Сохранить", "Сақтау", "Saqlash", "Save", None),
    ("garage_rent_button", "Арендовать", "Жалға алу", "Ijaraga olish", "Rent", "Кнопка аренды гаража"),
    ("house_buy_button", "Купить дом", "Үй сатып алу", "Uy sotib olish", "Buy house", None),
    ("house_sell_button", "Продать дом", "Үйді сату", "Uyni sotish", "Sell house", None),
    ("car_buy_title", "Покупка автомобиля", "Көлік сатып алу", "Avtomobil sotib olish", "Buy a car", None),
    ("business_title", "Бизнес", "Бизнес", "Biznes", "Business", None),
    ("taxi_job_title", "Такси", "Такси", "Taksi", "Taxi", None),
    ("faction_tab", "Фракция", "Фракция", "Fraksiya", "Faction", None),
    ("family_tab", "Семья", "Отбасы", "Oila", "Family", "Вкладка меню семьи"),
    ("family_invite", "{name} приглашает вас в семью {family}", "{name} сізді {family} отбасына шақырады", "{name} sizni {family} oilasiga taklif qilmoqda", "{name} invites you to the {family} family", None),
    ("family_leave_confirm", "Вы уверены, что хотите покинуть семью?", "Отбасыдан шыққыңыз келетініне сенімдісіз бе?", "Haqiqatan ham oiladan chiqmoqchimisiz?", "Are you sure you want to leave the family?", None),
    ("faction_join_success", "Вы вступили во фракцию {faction}", "Сіз {faction} фракциясына кірдіңіз", "Siz {faction} fraksiyasiga qoʻshildingiz", "You joined the {faction} faction", None),
    ("faction_kicked", "Вас исключили из фракции", "Сізді фракциядан шығарды", "Sizni fraksiyadan chiqarishdi", "You were removed from the faction", None),
    ("coins_balance", "Баланс: {amount} Grand Coins", "Баланс: {amount} Grand Coins", "Balans: {amount} Grand Coins", "Balance: {amount} Grand Coins", None),
    ("coins_buy_button", "Купить Grand Coins", "Grand Coins сатып алу", "Grand Coins sotib olish", "Buy Grand Coins", None),
    ("coins_bonus", "Бонус {count} Grand Coins за первое пополнение", "Алғашқы толтыру үшін {count} Grand Coins бонус", "Birinchi toʻldirish uchun {count} Grand Coins bonus", "{count} Grand Coins bonus for your first top-up", None),
    ("warn_received", "Вы получили варн от администратора {admin}. Причина: {reason}", "Сіз {admin} әкімшісінен варн алдыңыз. Себебі: {reason}", "Siz {admin} administratoridan varn oldingiz. Sabab: {reason}", "You received a warning from admin {admin}. Reason: {reason}", None),
    ("warn_count", "Варны: {count}/3", "Варндар: {count}/3", "Varnlar: {count}/3", "Warnings: {count}/3", None),
    ("mute_received", "Вам выдан мут на {minutes} мин.", "Сізге {minutes} минутқа мут берілді.", "Sizga {minutes} daqiqaga mut berildi.", "You have been muted for {minutes} min.", None),
    ("chat_placeholder", "Введите сообщение", "Хабарлама енгізіңіз", "Xabar kiriting", "Enter a message", "Подсказка в поле ввода чата"),
    ("chat_send_button", "Отправить", "Жіберу", "Yuborish", "Send", None),
    ("money_sent", "Вы перевели {amount}$ игроку {name}", "Сіз {name} ойыншысына {amount}$ аудардыңыз", "Siz {name} oʻyinchisiga {amount}$ oʻtkazdingiz", "You transferred {amount}$ to {name}", None),
    ("money_received", "Игрок {name} перевёл вам {amount}$", "{name} ойыншысы сізге {amount}$ аударды", "{name} oʻyinchisi sizga {amount}$ oʻtkazdi", "{name} sent you {amount}$", None),
    ("not_enough_money", "Недостаточно денег", "Ақша жеткіліксіз", "Pul yetarli emas", "Not enough money", None),
    ("bank_balance_low", "Недостаточно средств на балансе", "Баланста қаражат жеткіліксіз", "Balansda mablagʻ yetarli emas", "Insufficient balance", None),
    ("truck_job_desc", "Работа дальнобойщиком: доставляйте грузы на фуре между городами", "Жүк тасушы жұмысы: фурамен қалалар арасында жүк жеткізіңіз", "Yuk tashuvchi ishi: furada shaharlar orasida yuk yetkazing", "Trucker job: deliver cargo between cities in a truck", None),
    ("truck_rent_button", "Арендовать фуру", "Фураны жалға алу", "Furani ijaraga olish", "Rent a truck", None),
    ("police_title", "Полиция", "Полиция", "Politsiya", "Police", None),
    ("police_wanted", "Вы в розыске! Уровень: {level}", "Сіз іздеудесіз! Деңгей: {level}", "Siz qidiruvdasiz! Daraja: {level}", "You are wanted! Level: {level}", None),
    ("mayor_election", "Выборы мэра начнутся через {hours} ч.", "Әкім сайлауы {hours} сағаттан кейін басталады.", "Hokim saylovi {hours} soatdan keyin boshlanadi.", "Mayor election starts in {hours} h.", None),
    ("level_up", "Поздравляем! Вы достигли {level} уровня", "Құттықтаймыз! Сіз {level} деңгейге жеттіңіз", "Tabriklaymiz! Siz {level} darajaga yetdingiz", "Congratulations! You reached level {level}", None),
    ("daily_reward_title", "Ежедневная награда", "Күнделікті сыйлық", "Kundalik mukofot", "Daily reward", None),
    ("daily_reward_claim_button", "Забрать", "Алу", "Olish", "Claim", None),
    ("quest_completed", "Задание выполнено!", "Тапсырма орындалды!", "Topshiriq bajarildi!", "Quest completed!", None),
    ("quest_reward", "Награда: {amount}$ и {exp} опыта", "Сыйлық: {amount}$ және {exp} тәжірибе", "Mukofot: {amount}$ va {exp} tajriba", "Reward: {amount}$ and {exp} XP", None),
    ("settings_language", "Язык", "Тіл", "Til", "Language", None),
    ("settings_sound", "Звук", "Дыбыс", "Ovoz", "Sound", None),
    ("settings_graphics_quality", "Качество графики", "Графика сапасы", "Grafika sifati", "Graphics quality", None),
    ("auth_login_button", "Войти", "Кіру", "Kirish", "Log in", None),
    ("auth_register_button", "Регистрация", "Тіркелу", "Roʻyxatdan oʻtish", "Sign up", None),
    ("auth_password_hint", "Пароль должен содержать не менее 8 символов", "Құпиясөз кемінде 8 таңбадан тұруы керек", "Parol kamida 8 ta belgidan iborat boʻlishi kerak", "Password must be at least 8 characters", None),
    ("auth_wrong_password", "Неверный пароль", "Құпиясөз қате", "Parol notoʻgʻri", "Wrong password", None),
    ("server_connecting", "Подключение к серверу…", "Серверге қосылу…", "Serverga ulanish…", "Connecting to server…", None),
    ("server_full", "Сервер переполнен, попробуйте позже", "Сервер толы, кейінірек қайталап көріңіз", "Server toʻla, keyinroq urinib koʻring", "Server is full, try again later", None),
    ("friend_request", "{name} хочет добавить вас в друзья", "{name} сізді достарына қосқысы келеді", "{name} sizni doʻstlariga qoʻshmoqchi", "{name} wants to add you as a friend", None),
    ("friend_added", "{name} теперь ваш друг", "{name} енді сіздің досыңыз", "{name} endi sizning doʻstingiz", "{name} is now your friend", None),
    ("support_ticket_sent", "Ваше обращение отправлено. Администратор ответит в ближайшее время.", "Өтінішіңіз жіберілді. Әкімші жақын арада жауап береді.", "Murojaatingiz yuborildi. Administrator tez orada javob beradi.", "Your request has been sent. An administrator will reply soon.", None),
    ("support_title", "Поддержка", "Қолдау", "Yordam", "Support", None),
    ("house_rent_info", "Аренда дома стоит {price}$ в день", "Үйді жалға алу күніне {price}$ тұрады", "Uy ijarasi kuniga {price}$ turadi", "Renting the house costs {price}$ per day", None),
    ("business_income", "Доход бизнеса: {amount}$ в час", "Бизнес табысы: сағатына {amount}$", "Biznes daromadi: soatiga {amount}$", "Business income: {amount}$ per hour", None),
    ("business_buy_confirm", "Купить бизнес «{business}» за {price}$?", "«{business}» бизнесін {price}$ бағасына сатып аласыз ба?", "«{business}» biznesini {price}$ ga sotib olasizmi?", "Buy the business “{business}” for {price}$?", None),
    ("car_fuel_low", "Мало топлива! Заправьтесь на ближайшей АЗС", "Жанармай аз! Жақын маңдағы жанармай құю бекетіне барыңыз", "Yoqilgʻi kam! Eng yaqin yoqilgʻi quyish shoxobchasiga boring", "Low fuel! Refuel at the nearest gas station", None),
    ("car_repair_button", "Починить", "Жөндеу", "Taʼmirlash", "Repair", None),
    ("casino_title", "Казино", "Казино", "Kazino", "Casino", None),
    ("lottery_win", "Поздравляем, вы выиграли {amount}$ в лотерее!", "Құттықтаймыз, сіз лотереяда {amount}$ ұтып алдыңыз!", "Tabriklaymiz, siz lotereyada {amount}$ yutib oldingiz!", "Congratulations, you won {amount}$ in the lottery!", None),
    ("event_starts", "Событие «{event}» начнётся через {minutes} мин.", "«{event}» іс-шарасы {minutes} минуттан кейін басталады.", "«{event}» tadbiri {minutes} daqiqadan keyin boshlanadi.", "Event “{event}” starts in {minutes} min.", None),
    ("admin_jail", "Администратор {admin} посадил вас в тюрьму на {minutes} мин.", "{admin} әкімшісі сізді {minutes} минутқа түрмеге қамады.", "{admin} administratori sizni {minutes} daqiqaga qamoqqa oldi.", "Admin {admin} jailed you for {minutes} min.", None),
    ("report_player_button", "Пожаловаться", "Шағымдану", "Shikoyat qilish", "Report", None),
    ("vip_status", "VIP", "VIP", "VIP", "VIP", None),
    ("promo_code_hint", "Введите промокод", "Промокодты енгізіңіз", "Promokodni kiriting", "Enter promo code", None),
    ("items_count", "{count, plural, one{{count} предмет} few{{count} предмета} many{{count} предметов} other{{count} предмета}}", "{count, plural, other{{count} зат}}", "{count, plural, one{{count} ta buyum} other{{count} ta buyum}}", "{count, plural, one{{count} item} other{{count} items}}", "Количество предметов в инвентаре"),
    ("online_players", "Онлайн: {count}", "Онлайн: {count}", "Onlayn: {count}", "Online: {count}", None),
    ("online_friends", "Друзья онлайн", "Онлайн достар", "Onlayn doʻstlar", "Friends online", None),
    ("gps_button", "GPS", "GPS", "GPS", "GPS", None),
    ("house_owner_info", "Владелец: {name}", "Иесі: {name}", "Egasi: {name}", "Owner: {name}", None),
    ("job_salary", "Зарплата: {amount}$", "Жалақы: {amount}$", "Maosh: {amount}$", "Salary: {amount}$", None),
    ("job_quit_confirm", "Вы действительно хотите уволиться с работы?", "Жұмыстан шынымен шыққыңыз келе ме?", "Haqiqatan ham ishdan boʻshamoqchimisiz?", "Do you really want to quit your job?", None),
    ("tutorial_step_move", "Используйте джойстик, чтобы передвигаться по городу", "Қала бойынша жүру үшін джойстикті пайдаланыңыз", "Shahar boʻylab harakatlanish uchun joystikdan foydalaning", "Use the joystick to move around the city", None),
    ("tutorial_step_phone", "Откройте телефон, чтобы посмотреть задания", "Тапсырмаларды көру үшін телефонды ашыңыз", "Topshiriqlarni koʻrish uchun telefonni oching", "Open the phone to see your quests", None),
    ("phone_title", "Телефон", "Телефон", "Telefon", "Phone", None),
    ("phone_contacts_tab", "Контакты", "Контактілер", "Kontaktlar", "Contacts", None),
    ("phone_messages_tab", "Сообщения", "Хабарламалар", "Xabarlar", "Messages", None),
    ("bank_transfer_title", "Перевод", "Аудару", "Oʻtkazma", "Transfer", None),
    ("bank_deposit_button", "Пополнить", "Толтыру", "Toʻldirish", "Top up", None),
    ("family_members_count", "Участников в семье: {count}", "Отбасы мүшелері: {count}", "Oila aʼzolari: {count}", "Family members: {count}", None),
    ("family_leader", "Лидер семьи", "Отбасы басшысы", "Oila boshligʻi", "Family leader", None),
    ("faction_leader", "Лидер фракции", "Фракция басшысы", "Fraksiya rahbari", "Faction leader", None),
    ("faction_rank", "Ранг во фракции: {rank}", "Фракциядағы дәреже: {rank}", "Fraksiyadagi daraja: {rank}", "Faction rank: {rank}", None),
    ("gc_shop_title", "Магазин Grand Coins", "Grand Coins дүкені", "Grand Coins doʻkoni", "Grand Coins shop", None),
    ("ban_message", "Ваш аккаунт заблокирован до {date}", "Аккаунтыңыз {date} дейін бұғатталды", "Akkauntingiz {date} gacha bloklandi", "Your account is banned until {date}", None),
]

# Hand-made errors in the Kazakh file: key -> (issue_type, broken value or None to delete).
KK_ERRORS = {
    "settings_graphics_quality": ("untranslated", None),
    "phone_contacts_tab": ("untranslated", ""),
    "server_full": ("same_as_source", "Сервер переполнен, попробуйте позже"),
    "support_title": ("same_as_source", "Поддержка"),
    "bank_deposit_button": ("same_as_source", "Пополнить"),
    "money_received": ("placeholder_mismatch", "{аты} ойыншысы сізге {amount}$ аударды"),
    "police_wanted": ("placeholder_mismatch", "Сіз іздеудесіз! Деңгей:"),
    "items_count": ("plural_mismatch", "{count, plural, one{{count} зат}}"),
    "family_tab": ("glossary_violation", "Жанұя"),
    "coins_buy_button": ("glossary_violation", "Гранд Коинс сатып алу"),
    "garage_rent_button": ("length_overflow", "Жалға алу үшін басыңыз"),
    "car_repair_button": ("length_overflow", "Көлікті жөндеу орнына апару"),
    "quest_reward": ("machine_translation_suspect", "Сыйлық: {amount}$ и {exp} тәжірибе"),
    "tutorial_step_phone": ("machine_translation_suspect", "Үшін тапсырмаларды көру телефонды ашыңыз"),
    "support_ticket_sent": ("machine_translation_suspect", "Сіздің өтінішіңіз жіберілген болып табылады. Әкімші жақын арада жауап береді."),
    "shop_close_button": ("inconsistent_term", "Жабық"),
    "money_sent": ("suffix_harmony", "Сіз {name}-ға {amount}$ аудардыңыз"),
    "admin_jail": ("suffix_harmony", "{admin}-нің шешімімен сіз {minutes} минутқа түрмеге қамалдыңыз."),
    "auth_wrong_password": ("orthography", "Купиясөз қате"),
    "not_enough_money": ("orthography", "Акша жеткіліксіз"),
    "lottery_win": ("orthography", "Құттықтаймыз, сіз лотерeяда {amount}$ ұтып алдыңыз!"),  # Latin "e"
    "job_quit_confirm": ("wrong_language", "Haqiqatan ham ishdan boʻshamoqchimisiz?"),
    "daily_reward_title": ("wrong_language", "Kundalik mukofot"),
    "event_starts": ("wrong_language", "«{event}» тадбири {minutes} дақиқадан сўнг бошланади."),
    "chat_placeholder": ("wrong_language", "Введите текст сообщения"),
}


def write(name, data):
    (OUT / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    OUT.mkdir(exist_ok=True)
    langs = {"ru": 1, "kk": 2, "uz": 3, "en": 4}
    for lang, col in langs.items():
        data = {"@@locale": lang}
        for row in ROWS:
            key, value = row[0], row[col]
            if lang == "kk" and key in KK_ERRORS:
                value = KK_ERRORS[key][1]
                if value is None:
                    continue
            data[key] = value
            if lang == "ru" and row[5]:
                data[f"@{key}"] = {"description": row[5]}
        write(f"intl_{lang}.arb", data)
    write("expected_kk.json", [{"key": k, "issue_type": t} for k, (t, _) in KK_ERRORS.items()])
    print(f"{len(ROWS)} строк, {len(KK_ERRORS)} подложенных ошибок → {OUT}")


if __name__ == "__main__":
    main()
