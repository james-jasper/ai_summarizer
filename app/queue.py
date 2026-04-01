import aio_pika
import os
from dotenv import load_dotenv

load_dotenv()

QUEUE_NAME = os.getenv("QUEUE_NAME", "summarizer_jobs")


async def get_connection() -> aio_pika.RobustConnection:
    return await aio_pika.connect_robust(os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost/"))


async def publish_job(job_id: str) -> None:
    connection = await get_connection()
    async with connection:
        channel = await connection.channel()
        await channel.declare_queue(QUEUE_NAME, durable=True)
        await channel.default_exchange.publish(
            aio_pika.Message(
                body=job_id.encode(),
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key=QUEUE_NAME,
        )
