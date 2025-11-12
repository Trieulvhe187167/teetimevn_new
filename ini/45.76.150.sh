45.76.150.254
linuxuser
,Nj3grmA6nmHjV)G




cd ~/teetimevn
source venv/bin/activate




gunicorn "app:create_app()" -b 127.0.0.1:8000 --workers=4 

nohup gunicorn "app:create_app()" -b 127.0.0.1:8000 --workers=4 \
  > gunicorn.log 2>&1 &

gunicorn "app:create_app()" -b 127.0.0.1:8000 --workers 4 --log-level info


curl -i http://127.0.0.1:8000/

nohup gunicorn app:app -b 127.0.0.1:8000 --workers=4 > gunicorn.log 2>&1 &


pkill gunicorn  


sudo reboot




cd  E:\work\teetimevn

pybabel extract -F babel.cfg -o messages.pot .  


pybabel init -i messages.pot -d translations -l zh_CN
pybabel init -i messages.pot -d translations -l en
pybabel init -i messages.pot -d translations -l vi
pybabel init -i messages.pot -d translations -l ko
pybabel init -i messages.pot -d translations -l ja
pybabel init -i messages.pot -d translations -l zh_TW

pybabel compile -d translations




pybabel extract -F babel.cfg -k _ -o messages.pot .

pybabel update -i messages.pot -d translations
# Dòng lệnh này sẽ thêm các msgid mới vào mỗi file .po, giữ nguyên các msgstr cũ

pybabel compile -d translations


重启服务器后
# 1. 登录服务器并进入项目根目录
cd ~/teetimevn


# 2. 激活虚拟环境
source venv/bin/activate


# 3. 后台启动 Gunicorn（4 worker，监听 127.0.0.1:8000）
nohup venv/bin/gunicorn -w 4 -b 127.0.0.1:8000 app:app \
     --log-file gunicorn.log --log-level info &


# 4. 确认进程
ps aux | grep gunicorn


# 5. 看看日志（可选）
tail -f gunicorn.log




更新网站后重启服务
# 1. 终止所有 gunicorn worker + master
pkill -f "gunicorn.*app:app"


# 2. 重新启动
nohup venv/bin/gunicorn -w 4 -b 127.0.0.1:8000 app:app \
     --log-file gunicorn.log --log-level info &


