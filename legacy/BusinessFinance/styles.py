STYLES = """
<style>
    /* Базовые переходы и отступы */
    [data-testid="stMetric"],
    [data-testid="stSidebar"] button,
    [data-testid="stTextInput"] input,
    [data-testid="stNumberInput"] input,
    [data-testid="stDateInput"] input,
    [data-testid="stTextArea"] textarea,
    .final-result-box {
        transition: background-color 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease, filter 0.2s ease;
    }
    @media (prefers-reduced-motion: reduce) {
        [data-testid="stMetric"], [data-testid="stSidebar"] button,
        [data-testid="stTextInput"] input, [data-testid="stNumberInput"] input,
        [data-testid="stDateInput"] input, [data-testid="stTextArea"] textarea,
        .final-result-box { transition: none !important; }
    }

    /* Светлая тема: контент по центру, max 800px, padding 32px */
    .stApp { background: linear-gradient(180deg, #f0fdfa 0%, #f8fafc 30%, #ffffff 100%); }
    /* Хедер прозрачный */
    [data-testid="stHeader"],
    .stAppHeader,
    .st-emotion-cache-pq2g7.est0q591,
    header[data-testid="stHeader"] {
        background: transparent !important;
        border: none !important;
    }
    [data-testid="stAppViewContainer"] {
        width: 100%;
        margin-left: auto;
        margin-right: auto;
    }
    .stApp .block-container {
        width: 100%;
        max-width: 800px;
        margin-left: auto !important;
        margin-right: auto !important;
        padding: 0 32px 2rem 32px;
    }
    [data-testid="stAppViewContainer"] > div { max-width: 100%; }
    .st-emotion-cache-zy6yx3 { padding: 0 !important; }

    /* Чип в списке расходов (выравнивание и компактность) */
    .expense-chip {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        height: 32px;
        padding: 0 10px;
        border-radius: 999px;
        font-size: 0.85rem;
        line-height: 1;
        white-space: nowrap;
        border: 1px solid rgba(15, 118, 110, 0.18);
        background: rgba(15, 118, 110, 0.08);
        color: #0f766e;
        width: 100%;
        box-sizing: border-box;
        text-align: center;
    }
    .expense-chip-ours {
        border-color: rgba(13, 148, 136, 0.25);
        background: rgba(13, 148, 136, 0.10);
        color: #0f766e;
    }
    .expense-chip-partner {
        border-color: rgba(79, 70, 229, 0.25);
        background: rgba(79, 70, 229, 0.10);
        color: #4338ca;
    }

    /* Типографика светлая */
    h1 {
        font-weight: 700 !important;
        letter-spacing: -0.02em;
        line-height: 1.2;
        color: #0f766e !important;
        margin-bottom: 0.5rem !important;
    }
    .main-header {
        padding: 0.75rem 0 1.5rem 0;
        border-bottom: 2px solid #ccfbf1;
        margin-bottom: 1.75rem;
    }
    .main-header p { line-height: 1.5; }

    /* Метрики — контейнеры 20px, глубина через тень */
    [data-testid="stMetric"] {
        background: #ffffff;
        padding: 1.25rem 1.5rem;
        border-radius: 20px;
        box-shadow: 0 1px 3px rgba(13, 148, 136, 0.08);
        border-left: 4px solid #0d9488;
    }
    [data-testid="stMetric"]:hover {
        box-shadow: 0 4px 12px rgba(13, 148, 136, 0.12);
    }
    [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; }
    [data-testid="stHorizontalBlock"] > div { min-width: 180px !important; }
    [data-testid="stMetric"] label {
        color: #64748b !important;
        font-size: 0.875rem !important;
        line-height: 1.4;
    }
    [data-testid="stMetric"] [data-testid="stMetricValue"] {
        font-weight: 700 !important;
        color: #0f766e !important;
        letter-spacing: -0.01em;
    }

    /* Сайдбар светлая */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #f0fdfa 0%, #f1f5f9 100%) !important;
        border-right: 1px solid #e2e8f0 !important;
        text-align: left !important;
        width: 260px !important;
        min-width: 260px !important;
    }
    [data-testid="stSidebar"] > div,
    [data-testid="stSidebar"] [data-testid="stSidebarContent"] {
        align-items: flex-start !important;
        text-align: left !important;
    }
    [data-testid="stSidebar"] .stMarkdown,
    [data-testid="stSidebar"] .stCaption,
    [data-testid="stSidebar"] p { text-align: left !important; }
    [data-testid="stSidebar"] .stSelectbox label { font-weight: 600 !important; }
    [data-testid="stSidebar"] button {
        width: 100% !important;
        justify-content: flex-start !important;
        padding: 0.65rem 1rem !important;
        min-height: 44px !important;
        border-radius: 10px !important;
        margin-bottom: 6px !important;
        border: 1px solid #e2e8f0 !important;
        background: #ffffff !important;
        font-weight: 500 !important;
        box-shadow: 0 1px 2px rgba(0,0,0,0.04) !important;
        box-sizing: border-box !important;
    }
    [data-testid="stSidebar"] button:hover:not(:disabled) {
        background: #f0fdfa !important;
        border-color: #99f6e4 !important;
        box-shadow: 0 2px 6px rgba(13, 148, 136, 0.15) !important;
    }
    [data-testid="stSidebar"] button:focus-visible:not(:disabled) {
        outline: 2px solid #0d9488;
        outline-offset: 2px;
    }
    [data-testid="stSidebar"] button:disabled {
        opacity: 1 !important;
        cursor: default !important;
        border-color: #94a3b8 !important;
        color: #64748b !important;
    }

    /* Формы и карточки — radius 20px */
    [data-testid="stForm"] {
        background: #ffffff;
        padding: 1.5rem;
        border-radius: 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.06);
        border: 1px solid #e2e8f0;
    }
    .final-result-box {
        background: linear-gradient(135deg, #0d9488 0%, #0f766e 100%);
        color: white !important;
        padding: 1.5rem 2rem;
        border-radius: 20px;
        font-size: 1.5rem;
        font-weight: 700;
        line-height: 1.3;
        text-align: center;
        box-shadow: 0 8px 24px rgba(13, 148, 136, 0.25);
        margin: 1rem 0;
    }
    .final-result-negative {
        background: linear-gradient(135deg, #dc2626 0%, #b91c1c 100%) !important;
        box-shadow: 0 8px 24px rgba(220, 38, 38, 0.25) !important;
    }
    .stSuccess { border-radius: 10px !important; border-left: 4px solid #0d9488 !important; }
    .stError { border-radius: 10px !important; }

    /* Разделители */
    hr {
        border: none;
        border-top: 1px solid #e2e8f0;
        margin: 1.5rem 0;
    }
    [data-testid="stExpander"] {
        background: #ffffff;
        border-radius: 20px;
        border: 1px solid #e2e8f0;
        box-shadow: 0 1px 2px rgba(0,0,0,0.04);
    }
    [class*="st-emotion-cache-"],
    .eaeic2i0 { border-color: #e2e8f0 !important; }

    /* Инпуты светлая: 44px, radius 10px, focus ring */
    [data-testid="stTextInput"] input,
    [data-testid="stNumberInput"] input,
    [data-testid="stDateInput"] input,
    [data-testid="stTextArea"] textarea {
        border-radius: 10px !important;
        background-color: #ffffff !important;
        min-height: 44px !important;
        box-sizing: border-box;
        border: 1px solid #e2e8f0;
        box-shadow: 0 1px 2px rgba(0,0,0,0.04);
    }
    [data-testid="stTextInput"] input:focus,
    [data-testid="stNumberInput"] input:focus,
    [data-testid="stDateInput"] input:focus,
    [data-testid="stTextArea"] textarea:focus {
        border-color: #0d9488 !important;
        box-shadow: 0 0 0 3px rgba(13, 148, 136, 0.2) !important;
        outline: none;
    }
    [data-testid="stTextInput"] input:focus-visible,
    [data-testid="stNumberInput"] input:focus-visible,
    [data-testid="stDateInput"] input:focus-visible,
    [data-testid="stTextArea"] textarea:focus-visible {
        border-color: #0d9488 !important;
        box-shadow: 0 0 0 3px rgba(13, 148, 136, 0.2) !important;
        outline: none;
    }
    [data-testid="stSelectbox"] > div {
        border-radius: 10px !important;
        background-color: #ffffff !important;
        border: 1px solid #e2e8f0;
    }

    /* --- Тёмная тема — сочная и яркая --- */
    @media (prefers-color-scheme: dark) {
        /* Фон с градиентом */
        .stApp {
            background: linear-gradient(135deg, #0a0a0f 0%, #1a0f2e 25%, #0f1629 50%, #0a0a0f 100%) !important;
            background-attachment: fixed !important;
        }
        .stApp::before {
            content: '';
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: radial-gradient(circle at 20% 50%, rgba(99, 102, 241, 0.15) 0%, transparent 50%),
                        radial-gradient(circle at 80% 80%, rgba(168, 85, 247, 0.15) 0%, transparent 50%),
                        radial-gradient(circle at 40% 20%, rgba(59, 130, 246, 0.1) 0%, transparent 50%);
            pointer-events: none;
            z-index: 0;
        }
        /* Хедер прозрачный */
        [data-testid="stHeader"],
        .stAppHeader,
        .st-emotion-cache-pq2g7.est0q591,
        header[data-testid="stHeader"] {
            background: transparent !important;
            border: none !important;
        }

        /* Типографика с градиентом */
        h1 {
            background: linear-gradient(135deg, #ffffff 0%, #a5b4fc 50%, #818cf8 100%) !important;
            -webkit-background-clip: text !important;
            -webkit-text-fill-color: transparent !important;
            background-clip: text !important;
            letter-spacing: -0.02em;
            line-height: 1.2;
            filter: drop-shadow(0 0 20px rgba(129, 140, 248, 0.4));
        }
        .main-header {
            border-bottom: 2px solid transparent !important;
            border-image: linear-gradient(90deg, transparent, rgba(129, 140, 248, 0.4), transparent) 1 !important;
            padding-bottom: 1.5rem;
            position: relative;
        }
        .main-header::after {
            content: '';
            position: absolute;
            bottom: -2px;
            left: 0;
            right: 0;
            height: 2px;
            background: linear-gradient(90deg, transparent, rgba(129, 140, 248, 0.6), transparent);
            box-shadow: 0 0 10px rgba(129, 140, 248, 0.3);
        }
        .main-header p { color: rgba(196, 181, 253, 0.8) !important; }
        p, .stMarkdown, label { color: rgba(196, 181, 253, 0.75) !important; }

        /* Метрики с неоновым эффектом */
        [data-testid="stMetric"] {
            background: linear-gradient(135deg, rgba(30, 27, 75, 0.8) 0%, rgba(55, 48, 163, 0.4) 100%) !important;
            border-left: 4px solid transparent !important;
            border-image: linear-gradient(180deg, #818cf8, #6366f1, #8b5cf6) 1 !important;
            box-shadow: 0 4px 20px rgba(99, 102, 241, 0.2),
                        0 0 0 1px rgba(129, 140, 248, 0.1),
                        inset 0 1px 0 rgba(255, 255, 255, 0.1) !important;
            border-radius: 20px !important;
            backdrop-filter: blur(10px);
            position: relative;
            overflow: hidden;
        }
        [data-testid="stMetric"]::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.1), transparent);
            transition: left 0.5s ease;
        }
        [data-testid="stMetric"]:hover {
            background: linear-gradient(135deg, rgba(55, 48, 163, 0.6) 0%, rgba(99, 102, 241, 0.5) 100%) !important;
            box-shadow: 0 8px 30px rgba(99, 102, 241, 0.4),
                        0 0 0 1px rgba(129, 140, 248, 0.3),
                        inset 0 1px 0 rgba(255, 255, 255, 0.15),
                        0 0 40px rgba(129, 140, 248, 0.2) !important;
            transform: translateY(-2px);
        }
        [data-testid="stMetric"]:hover::before {
            left: 100%;
        }
        [data-testid="stMetric"] label {
            color: rgba(196, 181, 253, 0.7) !important;
            text-shadow: 0 0 10px rgba(196, 181, 253, 0.3);
        }
        [data-testid="stMetric"] [data-testid="stMetricValue"] {
            background: linear-gradient(135deg, #ffffff 0%, #c4b5fd 100%) !important;
            -webkit-background-clip: text !important;
            -webkit-text-fill-color: transparent !important;
            background-clip: text !important;
            font-weight: 700 !important;
            letter-spacing: -0.01em;
            filter: drop-shadow(0 0 8px rgba(196, 181, 253, 0.4));
        }

        /* Сайдбар с эффектом стекла */
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, rgba(30, 27, 75, 0.85) 0%, rgba(17, 24, 39, 0.9) 100%) !important;
            backdrop-filter: saturate(200%) blur(30px) brightness(1.1);
            -webkit-backdrop-filter: saturate(200%) blur(30px) brightness(1.1);
            border-right: 1px solid rgba(129, 140, 248, 0.2) !important;
            box-shadow: 2px 0 20px rgba(0, 0, 0, 0.5),
                        inset -1px 0 0 rgba(129, 140, 248, 0.1) !important;
        }
        [data-testid="stSidebar"] .stMarkdown,
        [data-testid="stSidebar"] p {
            color: rgba(196, 181, 253, 0.8) !important;
            text-shadow: 0 0 10px rgba(196, 181, 253, 0.2);
        }
        [data-testid="stSidebar"] button {
            border: 1px solid rgba(129, 140, 248, 0.2) !important;
            background: linear-gradient(135deg, rgba(55, 48, 163, 0.4) 0%, rgba(99, 102, 241, 0.3) 100%) !important;
            color: #c4b5fd !important;
            border-radius: 12px !important;
            font-weight: 500 !important;
            box-shadow: 0 2px 10px rgba(99, 102, 241, 0.15),
                        inset 0 1px 0 rgba(255, 255, 255, 0.1) !important;
            position: relative;
            overflow: hidden;
        }
        [data-testid="stSidebar"] button::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.15), transparent);
            transition: left 0.4s ease;
        }
        [data-testid="stSidebar"] button:hover:not(:disabled) {
            background: linear-gradient(135deg, rgba(99, 102, 241, 0.6) 0%, rgba(129, 140, 248, 0.5) 100%) !important;
            border-color: rgba(129, 140, 248, 0.5) !important;
            box-shadow: 0 4px 20px rgba(99, 102, 241, 0.3),
                        0 0 0 1px rgba(129, 140, 248, 0.3),
                        inset 0 1px 0 rgba(255, 255, 255, 0.2),
                        0 0 30px rgba(129, 140, 248, 0.2) !important;
            transform: translateX(2px);
            color: #ffffff !important;
        }
        [data-testid="stSidebar"] button:hover:not(:disabled)::before {
            left: 100%;
        }
        [data-testid="stSidebar"] button:focus-visible:not(:disabled) {
            outline: 2px solid #818cf8 !important;
            outline-offset: 2px !important;
            box-shadow: 0 0 0 4px rgba(129, 140, 248, 0.3),
                        0 4px 20px rgba(99, 102, 241, 0.3) !important;
        }
        [data-testid="stSidebar"] button:disabled {
            color: rgba(196, 181, 253, 0.3) !important;
            background: rgba(30, 27, 75, 0.3) !important;
            border-color: rgba(129, 140, 248, 0.1) !important;
            opacity: 0.5;
        }

        /* Формы с эффектом свечения */
        [data-testid="stForm"] {
            background: linear-gradient(135deg, rgba(30, 27, 75, 0.6) 0%, rgba(17, 24, 39, 0.7) 100%) !important;
            border: 1px solid rgba(129, 140, 248, 0.2) !important;
            border-radius: 20px !important;
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4),
                        0 0 0 1px rgba(129, 140, 248, 0.1),
                        inset 0 1px 0 rgba(255, 255, 255, 0.1) !important;
            backdrop-filter: blur(10px);
        }
        .final-result-box {
            background: linear-gradient(135deg, #6366f1 0%, #818cf8 50%, #a78bfa 100%) !important;
            color: #ffffff !important;
            border-radius: 20px !important;
            box-shadow: 0 10px 40px rgba(99, 102, 241, 0.5),
                        0 0 0 1px rgba(255, 255, 255, 0.2),
                        inset 0 1px 0 rgba(255, 255, 255, 0.3),
                        0 0 60px rgba(129, 140, 248, 0.4) !important;
            font-weight: 700 !important;
            line-height: 1.3 !important;
            position: relative;
            overflow: hidden;
        }
        .final-result-box::before {
            content: '';
            position: absolute;
            top: -50%;
            left: -50%;
            width: 200%;
            height: 200%;
            background: radial-gradient(circle, rgba(255, 255, 255, 0.2) 0%, transparent 70%);
            animation: shimmer 3s infinite;
        }
        @keyframes shimmer {
            0% { transform: translate(-50%, -50%) rotate(0deg); }
            100% { transform: translate(-50%, -50%) rotate(360deg); }
        }
        .final-result-negative {
            background: linear-gradient(135deg, #ef4444 0%, #f87171 50%, #fca5a5 100%) !important;
            box-shadow: 0 10px 40px rgba(239, 68, 68, 0.5),
                        0 0 0 1px rgba(255, 255, 255, 0.2),
                        inset 0 1px 0 rgba(255, 255, 255, 0.3),
                        0 0 60px rgba(239, 68, 68, 0.4) !important;
        }
        .stSuccess {
            border-left: 4px solid transparent !important;
            border-image: linear-gradient(180deg, #10b981, #34d399) 1 !important;
            background: linear-gradient(135deg, rgba(16, 185, 129, 0.1) 0%, rgba(52, 211, 153, 0.05) 100%) !important;
            box-shadow: 0 0 20px rgba(16, 185, 129, 0.2) !important;
        }
        .stError {
            border-left: 4px solid transparent !important;
            border-image: linear-gradient(180deg, #ef4444, #f87171) 1 !important;
            background: linear-gradient(135deg, rgba(239, 68, 68, 0.1) 0%, rgba(248, 113, 113, 0.05) 100%) !important;
            box-shadow: 0 0 20px rgba(239, 68, 68, 0.2) !important;
        }

        /* Разделители с градиентом */
        hr {
            border: none !important;
            height: 2px !important;
            background: linear-gradient(90deg, transparent, rgba(129, 140, 248, 0.5), transparent) !important;
            margin: 1.5rem 0 !important;
            box-shadow: 0 0 10px rgba(129, 140, 248, 0.3);
        }
        [data-testid="stExpander"] {
            background: linear-gradient(135deg, rgba(30, 27, 75, 0.5) 0%, rgba(17, 24, 39, 0.6) 100%) !important;
            border: 1px solid rgba(129, 140, 248, 0.2) !important;
            border-radius: 20px !important;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3),
                        inset 0 1px 0 rgba(255, 255, 255, 0.05) !important;
        }
        [class*="st-emotion-cache-"], .eaeic2i0 {
            border-color: rgba(129, 140, 248, 0.2) !important;
        }

        /* Инпуты с неоновым свечением */
        [data-testid="stTextInput"] input,
        [data-testid="stNumberInput"] input,
        [data-testid="stDateInput"] input,
        [data-testid="stTextArea"] textarea {
            background: linear-gradient(135deg, rgba(30, 27, 75, 0.6) 0%, rgba(17, 24, 39, 0.7) 100%) !important;
            border: 1px solid rgba(129, 140, 248, 0.3) !important;
            color: #ffffff !important;
            border-radius: 12px !important;
            min-height: 44px !important;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.3),
                        inset 0 1px 0 rgba(255, 255, 255, 0.05) !important;
            backdrop-filter: blur(10px);
        }
        [data-testid="stTextInput"] input::placeholder,
        [data-testid="stTextArea"] textarea::placeholder {
            color: rgba(196, 181, 253, 0.5) !important;
        }
        [data-testid="stTextInput"] input:focus,
        [data-testid="stNumberInput"] input:focus,
        [data-testid="stDateInput"] input:focus,
        [data-testid="stTextArea"] textarea:focus {
            border-color: #818cf8 !important;
            box-shadow: 0 0 0 3px rgba(129, 140, 248, 0.3),
                        0 4px 20px rgba(99, 102, 241, 0.4),
                        inset 0 1px 0 rgba(255, 255, 255, 0.1),
                        0 0 30px rgba(129, 140, 248, 0.3) !important;
            outline: none !important;
            background: linear-gradient(135deg, rgba(55, 48, 163, 0.7) 0%, rgba(30, 27, 75, 0.8) 100%) !important;
        }
        [data-testid="stTextInput"] input:focus-visible,
        [data-testid="stNumberInput"] input:focus-visible,
        [data-testid="stDateInput"] input:focus-visible,
        [data-testid="stTextArea"] textarea:focus-visible {
            border-color: #818cf8 !important;
            box-shadow: 0 0 0 4px rgba(129, 140, 248, 0.4),
                        0 4px 20px rgba(99, 102, 241, 0.4),
                        0 0 40px rgba(129, 140, 248, 0.4) !important;
            outline: none !important;
        }
        [data-testid="stSelectbox"] > div {
            background: linear-gradient(135deg, rgba(30, 27, 75, 0.6) 0%, rgba(17, 24, 39, 0.7) 100%) !important;
            border: 1px solid rgba(129, 140, 248, 0.3) !important;
            border-radius: 12px !important;
            color: #ffffff !important;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.3),
                        inset 0 1px 0 rgba(255, 255, 255, 0.05) !important;
        }
        [data-testid="stSelectbox"] > div:hover {
            border-color: rgba(129, 140, 248, 0.5) !important;
            box-shadow: 0 4px 15px rgba(99, 102, 241, 0.3) !important;
        }
        [data-testid="stSelectbox"] label {
            color: rgba(196, 181, 253, 0.8) !important;
            text-shadow: 0 0 10px rgba(196, 181, 253, 0.2);
        }

        /* Таблицы с эффектом стекла */
        [data-testid="stDataFrame"] {
            border-radius: 16px !important;
            overflow: hidden;
            background: linear-gradient(135deg, rgba(30, 27, 75, 0.4) 0%, rgba(17, 24, 39, 0.5) 100%) !important;
            border: 1px solid rgba(129, 140, 248, 0.2) !important;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3),
                        inset 0 1px 0 rgba(255, 255, 255, 0.05) !important;
        }
        [data-testid="stDataFrame"] table,
        .stDataFrame table {
            color: rgba(196, 181, 253, 0.9) !important;
        }
        [data-testid="stDataFrame"] th,
        .stDataFrame th {
            background: linear-gradient(135deg, rgba(99, 102, 241, 0.3) 0%, rgba(129, 140, 248, 0.2) 100%) !important;
            color: #c4b5fd !important;
            text-shadow: 0 0 10px rgba(196, 181, 253, 0.3);
        }
        [data-testid="stDataFrame"] td,
        .stDataFrame td {
            border-color: rgba(129, 140, 248, 0.15) !important;
        }
        [data-testid="stDataFrame"] tr:hover {
            background: rgba(99, 102, 241, 0.15) !important;
        }

        /* Чипы в списке расходов — в тон тёмной темы */
        .expense-chip {
            border-color: rgba(129, 140, 248, 0.25);
            background: rgba(129, 140, 248, 0.12);
            color: rgba(255, 255, 255, 0.92);
        }
        .expense-chip-ours {
            border-color: rgba(16, 185, 129, 0.28);
            background: rgba(16, 185, 129, 0.14);
            color: rgba(209, 250, 229, 0.95);
        }
        .expense-chip-partner {
            border-color: rgba(129, 140, 248, 0.28);
            background: rgba(129, 140, 248, 0.16);
            color: rgba(224, 231, 255, 0.95);
        }
    }
</style>
"""
