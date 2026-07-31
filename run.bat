@echo off
chcp 65001 >nul 2>&1
setlocal EnableDelayedExpansion

echo ========================================
echo   票据智能提取台 v7 - 一键启动
echo ========================================
echo.

:: 检查是否已存在 venv
if not exist "venv" (
    echo [1/3] 正在创建虚拟环境（首次启动需要几分钟）...
    python -m venv venv
    if errorlevel 1 (
        echo.
        echo 错误：未找到 Python，请先安装 Python 3.9+
        echo 下载地址：https://www.python.org/downloads/
        echo 安装时请勾选 "Add Python to PATH"
        pause
        exit /b 1
    )
    echo [1/3] 虚拟环境创建完成
) else (
    echo [1/3] 虚拟环境已存在
)

echo.
echo [2/3] 正在安装/更新依赖...
call venv\Scripts\activate.bat
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple >nul 2>&1
if errorlevel 1 (
    pip install -r requirements.txt
)
echo [2/3] 依赖安装完成
echo.
echo [3/3] 正在启动服务...
echo.
echo ========================================
echo   服务已启动！
echo   请在浏览器打开：http://localhost:5000
echo   按 Ctrl+C 可停止服务
echo ========================================
echo.

python app.py -p 5000 --host 0.0.0.0

pause