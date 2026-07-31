@echo off
chcp 65001 >nul 2>&1
setlocal

where python >nul 2>&1
if not errorlevel 1 (
    set "PYTHON=python"
    goto :python_found
)

where py >nul 2>&1
if not errorlevel 1 (
    py -3 --version >nul 2>&1
    if not errorlevel 1 (
        set "PYTHON=py -3"
        goto :python_found
    )
)

echo 错误：未找到可用的 Python 3，请先安装 Python 3.9+
echo 下载地址：https://www.python.org/downloads/
echo 安装时请勾选 "Add Python to PATH"
pause
exit /b 1

:python_found

echo ========================================
echo   票据智能提取台 v7 - 一键启动
echo ========================================
echo.

:: 检查是否已存在 venv
if not exist "venv" (
    echo [1/3] 正在创建虚拟环境（首次启动需要几分钟）...
    %PYTHON% -m venv venv
    if errorlevel 1 (
        echo.
        echo 错误：虚拟环境创建失败。
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
python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 (
    echo 清华镜像安装失败，正在改用 PyPI...
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo 错误：依赖安装失败，请检查网络和上方错误信息。
        pause
        exit /b 1
    )
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

python app.py --port 5000 --host 0.0.0.0

pause
