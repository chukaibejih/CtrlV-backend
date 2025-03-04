# CtrlV - Code Sharing at the Speed of Paste

CtrlV is more than just a code-sharing tool – it's a developer's quick share companion. We created a platform that eliminates the everyday friction of sharing code snippets. Whether you're debugging with a colleague, mentoring a junior developer, or just need to share a piece of code instantly, CtrlV makes it seamless.

Think of it as **AirDrop for code** – instant, clean, and zero friction. Paste your code, and within seconds, you get a **shareable link** with perfect syntax highlighting, **automatic language detection**, and a professional interface. No signup, no complicated steps – just pure, fast code sharing.

## Features
- **Instant Code Sharing:** Paste your code and get a link immediately.
- **Secure Access:** Each snippet is assigned a unique access token.
- **Expiration & One-Time View:** Set expiration times or make it viewable only once.
- **Analytics:** Track total snippets, active snippets, and language distribution.

## Tech Stack
- **Backend:** Django Rest Framework (DRF)
- **Database:** PostgreSQL
- **Deployment:** Render/Digital Ocean

---

## Installation & Setup
### 1. Clone the Repository
```sh
git clone https://github.com/your-username/ctrlv-backend.git
cd ctrlv-backend
```

### 2. Install Dependencies
We use **Poetry** for dependency management. Install it first if you haven't:
```sh
pip install poetry
```
Then, install the project dependencies:
```sh
poetry install
```

### 3. Configure Environment Variables
Create a `.env` file in the root directory and set the required environment variables:
```ini
SECRET_KEY=your_secret_key
DEBUG=True  # Set to False in production
DATABASE_URL=postgres://your_db_url
ALLOWED_HOSTS=*
```

### 4. Apply Migrations
```sh
poetry run python manage.py migrate
```

### 5. Collect Static Files (For Production)
```sh
poetry run python manage.py collectstatic --no-input
```

### 6. Run the Server
```sh
poetry run python manage.py runserver
```
Access the API at: `http://127.0.0.1:8000/`

---

## Deployment (Render)
Create a **build script** (`build.sh`) in the root directory:
```sh
#!/usr/bin/env bash
set -o errexit

poetry install --no-root
poetry run python manage.py collectstatic --no-input
poetry run python manage.py migrate
```
Then, configure your **Render settings**:
- **Runtime:** Python 3.x
- **Build Command:** `./build.sh`
- **Start Command:** `poetry run python manage.py runserver 0.0.0.0:8000`

---

## License
MIT License. See `LICENSE` for details.

---

