# Troupe Backend API 🌍🚀

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115.0-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Neon%20DB-336791?style=for-the-badge&logo=postgresql&logoColor=white)](https://neon.tech)
[![Redis](https://img.shields.io/badge/Upstash-Redis%20REST-DC382D?style=for-the-badge&logo=redis&logoColor=white)](https://upstash.com)
[![WebSockets](https://img.shields.io/badge/RealTime-WebSockets-010101?style=for-the-badge&logo=socketdotio&logoColor=white)](https://fastapi.tiangolo.com/advanced/websockets/)
[![Razorpay](https://img.shields.io/badge/Payments-Razorpay-0C2340?style=for-the-badge&logo=razorpay&logoColor=528FF0)](https://razorpay.com)

A high-performance, modular asynchronous REST and WebSocket API powering **Troupe** — a community-driven travel discovery and group trip coordination platform connecting travelers directly with verified trip organizers.

---

## 🌟 Key Capabilities

- **🔐 Robust JWT Authentication**: Access token & refresh token rotation, bcrypt password hashing, and role-based permissions (`traveler`, `organizer`).
- **🗺️ Multi-Step Trip Engine**: 6-stage structured trip lifecycle (Draft ➔ Itinerary ➔ Inclusions ➔ Pricing & Capacity ➔ Categories ➔ Story & FAQs ➔ Publish).
- **⚡ Real-Time Messaging & Presence**:
  - Full-duplex WebSocket connections for direct traveler-organizer communication.
  - Upstash Redis for presence tracking (online/offline heartbeat renewal) and chat caching.
  - QStash message queuing for asynchronous and resilient event distribution.
  - Firebase Cloud Messaging (FCM) fallback for offline push notifications.
  - Features: real-time delivery status (`SENDING`, `SENT`, `DELIVERED`, `READ`), message editing, soft-deletion, and thread replies.
- **💳 Seat Reservation & Razorpay Checkout**:
  - Concurrency-safe seat reservation holding with database row locks (`SELECT ... FOR UPDATE`) and idempotency enforcement.
  - 8-minute reservation time-to-live (TTL) with automated hold cleanup.
  - Razorpay order creation and HMAC-SHA256 webhook signature verification.
  - Responsive HTML Standard Checkout page with mobile deep linking.
- **📦 S3-Compatible Cloud Media Storage**: Supabase Storage integration with secure pre-signed upload URLs and verification hooks for trip thumbnails, itinerary photos, and avatars.
- **🔍 Full-Text Unified Search**: High-speed search filtering across destinations, trip titles, categories, budget ranges, and organizer profiles.

---

## 🏗️ System Architecture

```mermaid
graph TD
    Client[Mobile App / Web Client] -->|HTTPS REST| FastAPI[FastAPI Gateway]
    Client -->|WSS Connection| WSHandler[WebSocket Engine]
    
    FastAPI --> AuthMod[Auth & Users Module]
    FastAPI --> TripMod[Trips & Itinerary Module]
    FastAPI --> SearchMod[Unified Search Module]
    FastAPI --> UploadMod[Supabase Media Module]
    FastAPI --> PayMod[Payment & Seat Hold Module]
    
    WSHandler --> ConnMgr[In-Memory Connection Manager]
    WSHandler --> Redis[Upstash Redis: Presence & Cache]
    WSHandler --> QStash[QStash: Async Event Webhook]
    WSHandler --> FCM[Firebase: Push Notifications]
    
    PayMod --> Razorpay[Razorpay Gateway API]
    UploadMod --> Supabase[Supabase S3 Storage]
    
    AuthMod --> Postgres[(Neon PostgreSQL DB)]
    TripMod --> Postgres
    PayMod --> Postgres
    WSHandler --> Postgres
```

---

## 📂 Repository Structure

```
backend/
├── core/
│   ├── config.py           # Centralized environment & app settings
│   ├── database.py         # SQLAlchemy engine, session maker & declarative Base
│   ├── dependencies.py     # Auth guards (get_current_user, require_organizer)
│   ├── exceptions.py       # Global standardized exception handlers
│   └── security.py         # JWT generation, token decoding & bcrypt hashing
├── migrations/             # Alembic database migration scripts
├── modules/
│   ├── auth/               # Register, login, refresh token, logout
│   ├── users/              # User profile management, become organizer
│   ├── organizers/         # Organizer profiles, verification, reviews & trips
│   ├── trips/              # Multi-step trip creation, listing, filters, itineraries
│   ├── messaging/          # WebSockets, chats, presence, QStash & FCM integrations
│   ├── payment/            # Seat holds, Razorpay orders, webhooks & checkout page
│   ├── search/             # Unified search for trips and organizers
│   └── uploads/            # Pre-signed upload URLs with Supabase storage
├── utils/
│   └── responses.py        # Standard API envelope formatting helpers
├── alembic.ini             # Alembic configuration
├── main.py                 # ASGI entrypoint, middleware & router mounts
├── render.yaml             # Render deployment configuration
└── requirements.txt        # Production dependencies
```

---

## 🛠️ Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| **Framework** | [FastAPI](https://fastapi.tiangolo.com/) | Asynchronous web framework & OpenAPI documentation |
| **Server** | [Uvicorn](https://www.uvicorn.org/) | Lightning-fast ASGI production web server |
| **Database** | [PostgreSQL (Neon)](https://neon.tech/) | Serverless managed relational database |
| **ORM** | [SQLAlchemy 2.0](https://www.sqlalchemy.org/) | Modern asynchronous/sync ORM and repository layer |
| **Migrations** | [Alembic](https://alembic.sqlalchemy.org/) | Database schema evolution & version control |
| **Real-time & Caching** | [Upstash Redis](https://upstash.com/) | Serverless Redis for presence & session caching |
| **Async Tasks** | [Upstash QStash](https://upstash.com/docs/qstash) | Serverless message broker for reliable webhook dispatch |
| **Push Notifications** | [Firebase Admin SDK](https://firebase.google.com/) | Push delivery for offline message alerts |
| **Storage** | [Supabase Storage](https://supabase.com/storage) | Cloud object storage for media & banners |
| **Payments** | [Razorpay](https://razorpay.com/) | Payment orders, webhook verification & checkout |

---

## 🔌 API Reference Overview

Base URL: `/api/v1`

### 🔑 Authentication (`/api/v1/auth`)
- `POST /register` — Register a new traveler account
- `POST /login` — Authenticate credentials and receive access + refresh JWTs
- `POST /refresh` — Issue a new access token via valid refresh token
- `POST /logout` — Revoke and clean up user session

### 👤 Users (`/api/v1/user`)
- `GET /me` — Retrieve authenticated user profile
- `PATCH /me` — Update user profile details
- `PATCH /me/name` — Fast inline name update
- `POST /become-organizer` — Upgrade traveler account to trip organizer

### 🧭 Trips (`/api/v1/trips`)
- `GET /` — Browse published trips (supports pagination, budget, category, start date & sort)
- `POST /draft` — Initialize empty trip draft (organizer only)
- `PATCH /{trip_id}/step1` to `step6` — Incremental multi-step draft wizard updates
- `POST /{trip_id}/publish` — Validate and publish trip to public feed
- `GET /{trip_id}` — Complete trip details (itinerary, inclusions, organizer profile)
- `GET /{trip_id}/confirmation-data` — Real-time price and seat availability snapshot
- `GET /confirmed` — Retrieve user's confirmed trip bookings

### 💳 Payments & Seat Holds (`/api/v1/payments`)
- `POST /hold` — Acquire atomic seat hold lock and create Razorpay order
- `GET /hold/{confirmation_id}` — Query status of active seat reservation
- `POST /webhook` — Receive signed Razorpay webhook callbacks (`x-razorpay-signature`)
- `POST /cleanup` — Trigger cron expiration of stale pending holds
- `GET /checkout-page` — Render mobile-responsive Razorpay checkout webview

### 💬 Real-Time Messaging (`/api/v1/messaging`)
- `GET /chats` — List active user chats sorted by latest message
- `POST /fcm-token` — Register device token for push notifications
- `POST /qstash-webhook` — Signature-verified async event webhook
- `WS  /ws?token={jwt}` — Full-duplex WebSocket connection

#### WebSocket Protocol Events:
| Client ➔ Server | Server ➔ Client |
|---|---|
| `joinUserChat` | `connected` / `userChatJoined` |
| `sendMessage` | `newMessage` |
| `editMessage` | `messageEdited` |
| `deleteMessage` | `messageDeleted` |
| `markRead` | `messageStatusUpdate` |
| `presenceQuery` | `presenceResult` |
| `heartbeat` | `heartbeat_ack` |

### 🔍 Search & Discovery (`/api/v1/search`)
- `GET /` — Unified search across trips and organizers
- `GET /trips` — Dedicated trip keyword search
- `GET /organizers` — Dedicated organizer search

### ☁️ Media Uploads (`/api/v1/uploads`)
- `POST /presign` — Generate secure signed upload URL for trip/profile media
- `POST /confirm` — Confirm upload completion and sync database asset URL

---

## ⚙️ Environment Variables

Create a `.env` file in the `backend/` root directory:

```env
# Database
DATABASE_URL=postgresql://user:password@host/dbname?sslmode=require

# Authentication
JWT_SECRET_KEY=your_super_secret_jwt_key
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# Supabase Storage
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your_supabase_service_role_or_anon_key
SUPABASE_BUCKET=media
SUPABASE_PROFILE_PICS_BUCKET=profile_pics

# Upstash Redis & QStash
UPSTASH_REDIS_REST_URL=https://your-redis.upstash.io
UPSTASH_REDIS_REST_TOKEN=your_upstash_redis_token
QSTASH_URL=https://qstash.upstash.io
QSTASH_TOKEN=your_qstash_token
QSTASH_CURRENT_SIGNING_KEY=your_qstash_current_signing_key
QSTASH_NEXT_SIGNING_KEY=your_qstash_next_signing_key

# Firebase Cloud Messaging
FIREBASE_CREDENTIALS_PATH=firebase-credentials.json
# Or specify raw JSON:
# FIREBASE_CREDENTIALS_JSON={"type":"service_account",...}

# Razorpay Payments
RAZORPAY_KEY_ID=rzp_test_xxxxxx
RAZORPAY_SECRET_KEY=your_razorpay_secret
RAZORPAY_WEBHOOK_SECRET=your_razorpay_webhook_secret
```

---

## 🚀 Getting Started

### 1. Prerequisites
- Python 3.11+
- PostgreSQL database (or free tier at [Neon.tech](https://neon.tech))
- Virtual environment tool (`venv`)

### 2. Setup Virtual Environment
```bash
# Clone the repository and navigate to backend
git clone https://github.com/Sohamm24/Travel-Pinterest-Backend.git
cd Travel-Pinterest-Backend

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# Linux / macOS:
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Database Setup
Ensure your `DATABASE_URL` is configured in `.env`. On startup, FastAPI automatically verifies and creates the required database tables via SQLAlchemy metadata. To run migrations manually with Alembic:
```bash
alembic upgrade head
```

### 5. Run Development Server
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Once running:
- **Interactive OpenAPI Documentation**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **Alternative ReDoc Documentation**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **Health Check Endpoint**: [http://localhost:8000/api/v1/health](http://localhost:8000/api/v1/health)

---

## 🔒 Security Best Practices

- **Atomic Row-Level Locking**: High-concurrency seat reservation calls use Postgres row-level locks to prevent double-booking.
- **HMAC Webhook Verification**: Razorpay and QStash webhooks cryptographically verify request payload signatures before execution.
- **Credential Storage**: Sensitive passwords hashed with `bcrypt` (work factor 12).
- **CORS Configuration**: Configurable origin filtering for production deployment.

---

## 📄 License

This project is licensed under the MIT License — see the repository for full details.
