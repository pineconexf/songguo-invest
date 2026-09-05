# -*- coding: utf-8 -*-
# 云端静态站推送：读环境变量 CLOUD_HOST/CLOUD_USER/CLOUD_PWD，上传 dist.tgz -> 解压 -> nginx reload -> 验证
import os, paramiko

HOST = os.environ["CLOUD_HOST"]
USER = os.environ["CLOUD_USER"]
PWD  = os.environ["CLOUD_PWD"]
TGZ  = os.path.join(os.environ.get("TMP", "/tmp"), "pinecone-site.tgz")
ROOT = "/var/www/pinecone-lab"

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username=USER, password=PWD, timeout=15)

def run(cmd, t=90):
    si, so, se = c.exec_command(cmd, timeout=t)
    e = so.read().decode("utf-8", "replace") + se.read().decode("utf-8", "replace")
    print("$ " + cmd + "\n" + e.strip()[:700] + "\n")

sftp = c.open_sftp()
sftp.put(TGZ, "/tmp/pinecone-site.tgz")
sftp.close()
print("uploaded", TGZ)

run("mkdir -p %s && rm -rf %s/* && tar -xzf /tmp/pinecone-site.tgz -C %s && chmod -R o+rX %s" % (ROOT, ROOT, ROOT, ROOT))
run("nginx -t 2>&1 && systemctl reload nginx 2>&1 || systemctl restart nginx 2>&1")
run("curl -s -o /dev/null -w 'root_status=%{http_code}\n' http://127.0.0.1/")
run("curl -s http://127.0.0.1/ | grep -o '<title>[^<]*' || echo no-title")
c.close()
print("DONE")
