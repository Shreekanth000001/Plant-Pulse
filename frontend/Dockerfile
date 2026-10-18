FROM node:22.12.0-alpine

WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1

# Install dependencies
COPY package.json package-lock.json ./
RUN npm ci

# Copy application sources
COPY tsconfig.json next.config.ts next-env.d.ts eslint.config.mjs ./
COPY public ./public
COPY types ./types
COPY lib ./lib
COPY context ./context
COPY components ./components
COPY app ./app

# Build arguments for pre-baked client variables
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_WS_URL=ws://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_PUBLIC_WS_URL=$NEXT_PUBLIC_WS_URL

# Build the Next.js production artifact
RUN npm run build

ENV NODE_ENV=production

EXPOSE 3000

CMD ["npm", "start", "--", "-p", "3000", "-H", "0.0.0.0"]
