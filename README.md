# backend
Repository for Gyms backend infrastructure

# Setup in Visual Studio Code

- pull repository in VS Code and create python environment (venv).
- Docker needs to be installed on your maschine
- Install Docker extention to VS code
- Create run configuration type docker and project type flask
- need to have a mysql database (5.7.x) available, either run it within your docker or have a local installation
- Create .env file in root directory of the project and populate following properties:
    - DB_URL=mysql+pymysql://<dbuser>:<dbuserpw>@<dbhost name or ip>:3306/<dbname>
    - JWT_SECRET_KEY=<jwt secret key>
    - JWT_ALGORITHM=<HS256|HS512>
- Use Run and Debug to launch the application in your Local Docker
