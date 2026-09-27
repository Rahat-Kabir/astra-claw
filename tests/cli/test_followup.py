import asyncio

from astra_claw.cli.followup import FollowUpQueue, PromptBroker


def test_followup_queue_is_fifo():
    queue = FollowUpQueue()

    queue.put("first")
    queue.put("second")

    assert queue.size() == 2
    assert queue.pop() == "first"
    assert queue.pop() == "second"
    assert queue.pop() is None


def test_prompt_broker_close_releases_waiting_worker():
    async def scenario():
        broker = PromptBroker(asyncio.get_running_loop())
        worker = asyncio.create_task(
            asyncio.to_thread(broker.ask_from_worker, "answer> ")
        )
        await broker.next_request()
        broker.close()
        return await asyncio.wait_for(worker, timeout=1)

    assert asyncio.run(scenario()) == ""
